"""Dedicated Docker namespace gateway; never host networking.

The client HTTPS container shares this namespace. nftables timed source leases
protect both directions, including established TCP, if Python is killed/frozen.
Docker supervises PID 1; the worker owns provisioning and ordinary teardown.
"""
import argparse
import ipaddress
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from .gateway_channel import GatewayChannel, atomic_private, read_private
from .gateway_service import DurableLeases, GatewayWorker, exclusive
from .wireguard_gateway import GatewayError, GatewayPolicy, KernelWireGuard


def execute(*args, data=None):
    return subprocess.run(list(args), input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=2, check=False, env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL':'C'})


def checked(executor, *args, data=None):
    result = executor(*args, **({'data':data} if data is not None else {}))
    if result.returncode:
        raise GatewayError('gateway_container_command_failed')
    return result.stdout


class KernelLeaseGate:
    """Fixed nft vocabulary. No shell, untrusted scripts, NAT, or host rules."""
    def __init__(self, policy, client_port, listen_port, executor=execute):
        for port in (client_port, listen_port):
            if type(port) is not int or not 1024 <= port <= 65535:
                raise GatewayError('gateway_port_invalid')
        self.policy, self.client_port, self.listen_port, self.execute = policy, client_port, listen_port, executor

    def _script(self, script):
        checked(self.execute, 'nft', '-f', '-', data=script.encode('ascii'))

    def install(self):
        # Only this private namespace's table is replaced. Never flush ruleset.
        exists = self.execute('nft', 'list', 'table', 'inet', 'nova_gateway').returncode == 0
        self._script(('delete table inet nova_gateway\n' if exists else '') + f'''
table inet nova_gateway {{
 set live {{ type ipv4_addr; flags timeout; timeout 15s; size 50; }}
 chain input {{ type filter hook input priority -50; policy drop;
  iifname "lo" accept
  iifname "wg0" ip daddr {self.policy.gateway} ip saddr @live tcp dport {self.client_port} accept
  iifname "wg0" drop
  ct state established,related accept
  iifname "eth0" udp dport {self.listen_port} accept
  iifname "eth0" tcp dport {self.client_port} accept
 }}
 chain output {{ type filter hook output priority -50; policy accept;
  oifname "wg0" ip saddr {self.policy.gateway} ip daddr @live tcp sport {self.client_port} accept
  oifname "wg0" drop
 }}
 chain forward {{ type filter hook forward priority -50; policy drop; }}
}}
''')

    def authorize(self, peers, seconds):
        # Reserve a full command timeout: scheduling/application must not add
        # two extra seconds to the signed plan's lifetime. Subsecond/late work
        # stays closed. The timeout is in kernel time, independent of wall RTC.
        if not math.isfinite(seconds) or seconds > 15:
            raise GatewayError('gateway_firewall_lease_invalid')
        milliseconds = math.floor((seconds-2)*1000)
        if milliseconds <= 0:
            raise GatewayError('gateway_firewall_lease_expired')
        addresses = []
        network = ipaddress.IPv4Network(self.policy.pool)
        for peer in peers:
            route = ipaddress.IPv4Network(peer['address'])
            if (route.prefixlen != 32 or route.network_address not in network
                    or str(route.network_address) == self.policy.gateway
                    or route.network_address in (network.network_address, network.broadcast_address)):
                raise GatewayError('gateway_firewall_address_invalid')
            addresses.append(str(route.network_address))
        if len(addresses) > 50 or len(addresses) != len(set(addresses)):
            raise GatewayError('gateway_firewall_address_invalid')
        script = 'flush set inet nova_gateway live\n'
        if addresses:
            values = ', '.join(address+' timeout '+str(milliseconds)+'ms' for address in sorted(addresses))
            script += 'add element inet nova_gateway live { '+values+' }\n'
        self._script(script)

    def close(self):
        self._script('flush set inet nova_gateway live\n')


def load(path):
    value = json.loads(read_private(path, 8192))
    if (set(value) != {'schema_version','policy','client_port','listen_port'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1):
        raise GatewayError('gateway_container_configuration_invalid')
    policy = GatewayPolicy(**value['policy'])
    KernelLeaseGate(policy, value['client_port'], value['listen_port'])
    return value, policy


def provision(policy, gate, *, executor=execute, private_key='/identity/wireguard.key'):
    namespace = os.readlink('/proc/self/ns/net')
    backend = KernelWireGuard(executor, 'wg0', local_namespace=namespace)
    public = checked(executor, 'wg', 'pubkey', data=read_private(private_key, 45)).decode('ascii').strip()
    if public != policy.public_key:
        raise GatewayError('gateway_private_identity_mismatch')
    # Refuse overlap with the Docker underlay, including a user-selected subnet.
    interfaces = json.loads(checked(executor, 'ip', '-j', '-4', 'addr', 'show'))
    pool = ipaddress.IPv4Network(policy.pool)
    for link in interfaces:
        if link['ifname'] == 'wg0': continue
        for address in link.get('addr_info', []):
            if pool.overlaps(ipaddress.IPv4Network(str(address['local'])+'/'+str(address['prefixlen']), strict=False)):
                raise GatewayError('gateway_underlay_overlap')
    old = executor('ip', 'link', 'show', 'dev', 'wg0').returncode == 0
    if old:
        backend.verify_scope(policy)  # never adopt another interface or key
    gate.install()  # closes access BEFORE modifying/restoring a peer/interface
    if old:
        checked(executor, 'ip', 'link', 'delete', 'dev', 'wg0')
    checked(executor, 'ip', 'link', 'add', 'dev', 'wg0', 'type', 'wireguard')
    try:
        checked(executor, 'ip', 'link', 'set', 'dev', 'wg0', 'alias', 'nova-wireguard-v1:'+policy.server_id)
        checked(executor, 'wg', 'set', 'wg0', 'private-key', str(private_key), 'listen-port', str(gate.listen_port))
        checked(executor, 'ip', 'addr', 'add', policy.gateway+'/32', 'dev', 'wg0')
        checked(executor, 'ip', 'link', 'set', 'dev', 'wg0', 'mtu', '1280', 'up')
        checked(executor, 'ip', 'route', 'add', policy.pool, 'dev', 'wg0')
        backend.verify_scope(policy)
    except Exception:
        # The link was created by this invocation; the namespace lock is held.
        executor('ip', 'link', 'delete', 'dev', 'wg0')
        raise
    return backend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--health', action='store_true')
    args = parser.parse_args()
    if args.health:
        try:
            stamp = float(Path('/run/nova-gateway/healthy').read_text())
            return 0 if 0 <= time.monotonic()-stamp < 5 else 1
        except (OSError, ValueError): return 1
    stopping = threading.Event()
    for kind in (signal.SIGTERM, signal.SIGINT):
        signal.signal(kind, lambda *_: stopping.set())
    try:
        if sys.platform != 'linux' or os.geteuid() != 0 or not Path('/.dockerenv').is_file():
            raise GatewayError('dedicated_docker_gateway_required')
        # Docker sets these namespaced sysctls; the process cannot alter host ones.
        if Path('/proc/sys/net/ipv4/ip_forward').read_text().strip() != '0':
            raise GatewayError('gateway_forwarding_must_be_disabled')
        config, policy = load('/identity/gateway.json')
        channel = GatewayChannel('/channel', '/identity/channel.key')
        gate = KernelLeaseGate(policy, config['client_port'], config['listen_port'])
        with exclusive('/leases', 'container'):
            backend = provision(policy, gate)
            try:
                worker = GatewayWorker(policy, backend, channel, DurableLeases('/leases', policy), gate=gate)
                worker.stop()
                while not stopping.is_set():
                    if worker.tick():
                        atomic_private('/run/nova-gateway/healthy', str(time.monotonic()).encode('ascii'))
                    else:
                        Path('/run/nova-gateway/healthy').unlink(missing_ok=True)
                    stopping.wait(1)
            finally:
                gate.close()
                backend.verify_scope(policy)
                checked(execute, 'ip', 'link', 'delete', 'dev', 'wg0')
    except Exception as error:
        # GatewayError contains only our fixed public diagnostic vocabulary.
        code=str(error) if isinstance(error,GatewayError) else type(error).__name__
        print('NOVA gateway: '+code+'; access is not confirmed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
