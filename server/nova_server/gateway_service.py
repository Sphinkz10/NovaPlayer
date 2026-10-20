"""Opt-in Linux WireGuard worker for an already provisioned dedicated namespace.

Run with `python -m nova_server.gateway_service --config /private/gateway.json`.
Local config supplies policy/paths; mailbox messages cannot supply executors,
interfaces, routes, firewall rules or private keys. This is not a NAS installer.
"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import stat
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

from .gateway_channel import GatewayChannel, canonical, private_directory, read_private
from .wireguard_gateway import GatewayError, GatewayPolicy, GatewaySnapshot, KernelWireGuard, clear_owned, reconcile, _current


@contextmanager
def exclusive(directory, role):
    """Kernel lock, released even after SIGKILL; never unlink a lock inode."""
    if sys.platform != 'linux':
        raise GatewayError('linux_gateway_service_required')
    import fcntl
    directory = private_directory(directory)
    fd = os.open(directory / (role+'.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise GatewayError('gateway_regular_lock_required')
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise GatewayError('gateway_process_already_running') from None
        yield
    finally:
        os.close(fd)


class DurableLeases:
    def __init__(self, directory, policy):
        directory = private_directory(directory)
        self.path = directory / 'leases.sqlite3'
        if self.path.exists() or self.path.is_symlink():
            read_private(self.path, 1024*1024)
        # Create privately before SQLite opens it; the private parent prevents
        # replacement by another principal. The service holds an exclusive lock.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        self.policy = policy
        with self._db() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS identity(policy TEXT NOT NULL);'
                'CREATE TABLE IF NOT EXISTS leases(device_id TEXT PRIMARY KEY, public_key TEXT UNIQUE NOT NULL, '
                'address TEXT UNIQUE NOT NULL);')
            expected = canonical(asdict(policy)).decode()
            rows = db.execute('SELECT policy FROM identity').fetchall()
            if rows and rows != [(expected,)]:
                raise GatewayError('gateway_lease_identity_changed')
            if not rows:
                db.execute('INSERT INTO identity(policy) VALUES(?)', (expected,))

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db: yield db
        finally: db.close()

    def assign(self, snapshot, observed):
        desired = {peer.device_id: peer.public_key for peer in snapshot.peers}
        if len(desired) != len(snapshot.peers) or len(set(desired.values())) != len(desired):
            raise GatewayError('gateway_duplicate_peer')
        network = ipaddress.IPv4Network(self.policy.pool)
        available = [str(ip)+'/32' for ip in network.hosts() if str(ip) != self.policy.gateway]
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT device_id,public_key,address FROM leases').fetchall()
            if any(address not in available for _, _, address in previous):
                raise GatewayError('gateway_invalid_saved_lease')
            assigned = {public: address for device, public, address in previous if desired.get(device) == public}
            used = set(assigned.values())
            for device, public in sorted(desired.items()):
                if public in assigned: continue
                routes = observed.get(public, ())
                address = routes[0] if len(routes) == 1 and routes[0] in available and routes[0] not in used else None
                if address is None:
                    address = next((value for value in available if value not in used), None)
                if address is None:
                    raise GatewayError('gateway_address_pool_exhausted')
                assigned[public] = address; used.add(address)
            rows = [(device, public, assigned[public]) for device, public in sorted(desired.items())]
            if sorted(previous) != rows:
                db.execute('DELETE FROM leases')
                db.executemany('INSERT INTO leases VALUES(?,?,?)', rows)
            # Commit before touching the kernel: a crash cannot announce an IP
            # that will be silently reassigned when the interface is rebuilt.
            return assigned


class GatewayWorker:
    def __init__(self, policy, backend, channel, leases, *, clock=time.time, monotonic=time.monotonic):
        self.policy, self.backend, self.channel, self.leases = policy, backend, channel, leases
        self.clock, self.monotonic = clock, monotonic
        self.seen = {}  # replay deadlines are monotonic and never extended
        self.latest_wall = 0

    def tick(self):
        plan = None
        try:
            plan = self.channel.read('plan')
            if set(plan) != {'schema_version', 'publisher_id', 'plan_id', 'snapshot'} or type(plan['schema_version']) is not int or plan['schema_version'] != 1:
                raise GatewayError('gateway_plan_invalid')
            for identity in ('publisher_id', 'plan_id'):
                if str(uuid.UUID(plan[identity])) != plan[identity]:
                    raise GatewayError('gateway_plan_invalid')
            snapshot = GatewaySnapshot.model_validate(plan['snapshot'])
            now, mono = int(self.clock()), self.monotonic()
            if now < self.latest_wall:
                raise GatewayError('gateway_clock_rollback')
            self.latest_wall = now
            _current(snapshot, self.policy, now)
            identity = (plan['publisher_id'], plan['plan_id'])
            fingerprint = canonical(plan)
            # Cache entries until wall expiry as well as monotonic expiry. Clock
            # rollback cannot turn a previously expired plan into a new lease.
            previous = self.seen.get(identity)
            if previous is None:
                if len(self.seen) >= 64:
                    self.seen = {key: value for key, value in self.seen.items() if value[2] > now}
                if len(self.seen) >= 64:
                    raise GatewayError('gateway_plan_replay_window_full')
                previous = (fingerprint, mono+snapshot.expires_at-now, snapshot.expires_at)
                self.seen[identity] = previous
            if previous[0] != fingerprint or previous[1] <= mono:
                raise GatewayError('gateway_plan_replayed')
            self.backend.verify_scope(self.policy)
            assigned = self.leases.assign(snapshot, self.backend.peers())
            def guarded_clock():
                if self.monotonic() >= previous[1]:
                    raise GatewayError('gateway_plan_expired')
                return self.clock()
            result = reconcile(plan['snapshot'], self.policy, self.backend, clock=guarded_clock, assignments=assigned)
            report = {'schema_version': 1, 'publisher_id': plan['publisher_id'], 'plan_id': plan['plan_id'],
                      'observed_at': int(self.clock()), 'result': result}
            self.channel.write('observation', report)
            return True
        except Exception:
            # No raw errors, commands, filesystem paths or key material are
            # returned. Even malformed/stale transport clears owned peers.
            self.stop()
            return False

    def stop(self):
        removed = False
        try:
            clear_owned(self.policy, self.backend)
            removed = True
        except Exception: pass
        # Replace a previous success immediately, including when cleanup fails.
        try:
            self.channel.write('observation', {'schema_version': 1, 'state': 'not_verified',
                'configuration_observed': False, 'cleanup_confirmed': removed})
        except Exception: pass
        return removed

    def run(self, stopping, *, interval=1):
        try:
            # Never preserve peers from a previous worker while waiting for its
            # first fresh, authenticated plan.
            self.stop()
            while not stopping.is_set():
                self.tick()
                stopping.wait(interval)
        finally:
            self.stop()


def load_config(path):
    config = json.loads(read_private(path, 8192))
    fields = {'schema_version', 'policy', 'namespace', 'interface', 'channel_directory', 'secret_file', 'lease_directory'}
    if set(config) != fields or type(config['schema_version']) is not int or config['schema_version'] != 1:
        raise GatewayError('gateway_local_configuration_invalid')
    if not isinstance(config['namespace'], str) or not re.fullmatch(r'nova-wg-[a-z0-9]{1,24}', config['namespace']):
        raise GatewayError('gateway_namespace_invalid')
    for field in ('channel_directory', 'secret_file', 'lease_directory'):
        if not isinstance(config[field], str) or not Path(config[field]).is_absolute():
            raise GatewayError('gateway_absolute_local_path_required')
    policy = GatewayPolicy(**config['policy'])
    if private_directory(config['channel_directory']).resolve() == private_directory(config['lease_directory']).resolve():
        raise GatewayError('gateway_separate_lease_directory_required')
    return config, policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    try:
        if sys.platform != 'linux' or os.geteuid() != 0:
            raise GatewayError('linux_host_gateway_worker_required')
        config, policy = load_config(args.config)
        # The executable and prefix are fixed. Only local, private configuration
        # supplies the validated namespace/interface. No shell, sudo or PATH lookup.
        def execute(*argv):
            return subprocess.run(['/usr/sbin/ip', 'netns', 'exec', config['namespace'], *argv],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=2, check=False, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
        backend = KernelWireGuard(execute, config['interface'])
        channel = GatewayChannel(config['channel_directory'], config['secret_file'])
        stopping = threading.Event()
        for kind in (signal.SIGTERM, signal.SIGINT):
            signal.signal(kind, lambda *_: stopping.set())
        with exclusive(config['channel_directory'], 'worker'):
            try:
                backend.verify_scope(policy)
                leases = DurableLeases(config['lease_directory'], policy)
                GatewayWorker(policy, backend, channel, leases).run(stopping)
            finally:
                GatewayWorker(policy, backend, channel, None).stop()
    except Exception:
        print('NOVA gateway: startup failed; configuration/removal not confirmed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
