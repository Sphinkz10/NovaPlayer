"""Authenticated local mailbox; no network listener, admin session or commands.

Both processes and the local operator are trusted. The private shared directory
contains public plans/observations only. The 32-byte channel secret is supplied
separately, never through HTTP. Atomic replacements prevent partial reads.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import threading
import time
import uuid

from .wireguard_gateway import GatewayError, GatewaySnapshot

MAX_FRAME = 32768


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def private_directory(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or (os.name == 'posix' and info.st_mode & 0o077):
        raise GatewayError('gateway_private_directory_required')
    return path


def read_private(path, maximum=MAX_FRAME):
    path = Path(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise GatewayError('gateway_regular_file_required')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_size > maximum
                or (os.name == 'posix' and info.st_mode & 0o077)):
            raise GatewayError('gateway_private_file_required')
        raw = source.read(maximum+1)
        if len(raw) > maximum:
            raise GatewayError('gateway_frame_too_large')
        return raw


def atomic_private(path, raw):
    path = Path(path)
    directory = private_directory(path.parent)
    temporary = directory / ('.'+path.name+'.'+secrets.token_hex(12))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as target:
            # A host root worker may write to a private volume owned by the Core UID.
            if os.name == 'posix' and os.geteuid() == 0:
                owner = directory.stat()
                os.fchown(target.fileno(), owner.st_uid, owner.st_gid)
            target.write(raw); target.flush(); os.fsync(target.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


class GatewayChannel:
    def __init__(self, directory, secret_file):
        self.directory = private_directory(directory)
        self.secret = read_private(secret_file, 32)
        if len(self.secret) != 32:
            raise GatewayError('gateway_channel_key_required')

    def write(self, role, payload):
        if role not in ('plan', 'observation'):
            raise GatewayError('gateway_channel_role_invalid')
        signature = hmac.new(self.secret, role.encode()+b'\0'+canonical(payload), hashlib.sha256).hexdigest()
        raw = canonical({'payload': payload, 'signature': signature})
        if len(raw) > MAX_FRAME:
            raise GatewayError('gateway_frame_too_large')
        atomic_private(self.directory / (role+'.json'), raw)

    def read(self, role):
        if role not in ('plan', 'observation'):
            raise GatewayError('gateway_channel_role_invalid')
        try:
            envelope = json.loads(read_private(self.directory / (role+'.json')))
            if set(envelope) != {'payload', 'signature'} or not isinstance(envelope['signature'], str):
                raise ValueError()
            expected = hmac.new(self.secret, role.encode()+b'\0'+canonical(envelope['payload']), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, envelope['signature']):
                raise ValueError()
            return envelope['payload']
        except (ValueError, TypeError, KeyError):
            raise GatewayError('gateway_channel_authentication_failed') from None


class GatewayPublisher:
    """Single Core publisher; observations must match this boot and live approvals.

    Wall-clock validity and monotonic deadlines both apply. An earlier report is
    never accepted after a Core restart, revocation or peer-list change.
    """
    def __init__(self, enrollments, channel, *, clock=time.time, monotonic=time.monotonic):
        self.enrollments, self.channel = enrollments, channel
        self.clock, self.monotonic = clock, monotonic
        self.identity = str(uuid.uuid4())
        self.pending = {}
        self.lock = threading.RLock()
        self.active = False

    def publish(self):
        with self.lock:
            snapshot = self.enrollments.gateway_plan()
            plan = {'schema_version': 1, 'publisher_id': self.identity,
                    'plan_id': str(uuid.uuid4()), 'snapshot': snapshot}
            self.channel.write('plan', plan)
            now = self.monotonic()
            self.pending = {key: value for key, value in self.pending.items() if value[1] > now}
            self.pending[plan['plan_id']] = (plan, now+max(0, snapshot['expires_at']-int(self.clock())))
            return plan

    def status(self):
        unavailable = {'state': 'not_verified', 'configuration_observed': False,
                       'handshake_verified': False, 'remote_access_enabled': False, 'peers': []}
        with self.lock:
            if not self.active:
                return unavailable
            try:
                report = self.channel.read('observation')
                if set(report) != {'schema_version', 'publisher_id', 'plan_id', 'observed_at', 'result'}:
                    return unavailable
                entry = self.pending.get(report['plan_id'])
                if (report['schema_version'] != 1 or report['publisher_id'] != self.identity
                        or entry is None or entry[1] <= self.monotonic()):
                    return unavailable
                plan = entry[0]; snapshot = GatewaySnapshot.model_validate(plan['snapshot'])
                now = int(self.clock())
                if (type(report['observed_at']) is not int
                        or not snapshot.issued_at <= report['observed_at'] <= now < snapshot.expires_at):
                    return unavailable
                current = self.enrollments.gateway_plan()
                if current['server_id'] != snapshot.server_id or current['peers'] != plan['snapshot']['peers']:
                    return unavailable
                result = report['result']
                if (set(result) != {'configuration_observed', 'handshake_verified', 'changed_operations', 'server_id', 'peers'}
                        or result['configuration_observed'] is not True or result['handshake_verified'] is not False
                        or result['server_id'] != snapshot.server_id):
                    return unavailable
                wanted = {(peer.device_id, peer.public_key) for peer in snapshot.peers}
                peers = result['peers']
                if len(peers) != len(wanted) or {(peer['device_id'], peer['public_key']) for peer in peers} != wanted:
                    return unavailable
                # The trusted worker owns address policy; the Core checks report
                # structure and never distributes these observations to a TV.
                import ipaddress
                addresses = []
                for peer in peers:
                    if set(peer) != {'device_id', 'public_key', 'address'}:
                        return unavailable
                    address = ipaddress.IPv4Network(peer['address'])
                    if address.prefixlen != 32 or not address.is_private:
                        return unavailable
                    addresses.append(str(address))
                if len(set(addresses)) != len(addresses):
                    return unavailable
                return {**unavailable, 'state': 'configuration_observed', 'configuration_observed': True,
                        'observed_at': report['observed_at'], 'expires_at': snapshot.expires_at,
                        'valid_for_seconds': max(0, min(snapshot.expires_at-now, entry[1]-self.monotonic())),
                        'peers': peers}
            except (OSError, ValueError, TypeError, KeyError, GatewayError):
                return unavailable
