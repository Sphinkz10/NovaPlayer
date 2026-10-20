"""Restricted peer reconciliation for a dedicated WireGuard network namespace.

Library adapter, not an installed background agent. The trusted caller supplies
the namespace executor and local policy; HTTP requests never supply commands,
interface names, addresses, private keys or that executor. No routes, firewall,
interface creation or private-key operations are performed here.
"""
import base64
import ipaddress
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from .connect import PRIVATE_NETWORKS
from .device_api import Payload
from .wireguard import validate_public_key


class GatewayError(Exception):
    """Safe public diagnostic; never carries a command output or key material."""


class PeerIntent(Payload):
    device_id: str
    public_key: str
    _key = field_validator('public_key')(validate_public_key)

    @field_validator('device_id')
    @classmethod
    def identity(cls, value):
        if str(uuid.UUID(value)) != value:
            raise ValueError('Invalid device identity')
        return value


class GatewaySnapshot(Payload):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal[1]
    server_id: str
    issued_at: int = Field(strict=True, ge=1)
    expires_at: int = Field(strict=True, ge=1)
    peers: list[PeerIntent] = Field(max_length=50)


@dataclass(frozen=True)
class GatewayPolicy:
    server_id: str
    public_key: str
    pool: str
    gateway: str

    def __post_init__(self):
        if str(uuid.UUID(self.server_id)) != self.server_id:
            raise ValueError('Invalid server identity')
        validate_public_key(self.public_key)
        network = ipaddress.IPv4Network(self.pool)
        address = ipaddress.IPv4Address(self.gateway)
        if (not 24 <= network.prefixlen <= 30 or not any(network.subnet_of(n) for n in PRIVATE_NETWORKS)
                or address not in network or address in (network.network_address, network.broadcast_address)):
            raise ValueError('Dedicated private gateway pool required')


def _current(snapshot, policy, now):
    if (snapshot.server_id != policy.server_id or not snapshot.issued_at <= now < snapshot.expires_at
            or not 0 < snapshot.expires_at-snapshot.issued_at <= 15):
        raise GatewayError('gateway_snapshot_expired_or_mismatched')


def reconcile(payload, policy, backend, *, clock=time.time, assignments=None):
    """One exclusive caller, one short-lived authoritative snapshot, full readback.

    Retain valid addresses already observed on this dedicated interface; new peers
    use free /32s from the local policy. Unknown or broad peers are removed before
    adding any desired peer. Success confirms configuration, not connectivity.
    A trusted service may supply durable assignments. Never call this against an
    existing shared VPN interface.
    """
    snapshot = GatewaySnapshot.model_validate(payload)
    _current(snapshot, policy, int(clock()))
    desired = {peer.public_key: peer.device_id for peer in snapshot.peers}
    if len(desired) != len(snapshot.peers) or len(set(desired.values())) != len(desired):
        raise GatewayError('gateway_duplicate_peer')
    backend.verify_scope(policy)
    observed = backend.peers()
    network = ipaddress.IPv4Network(policy.pool)
    available = [str(ip)+'/32' for ip in network.hosts() if str(ip) != policy.gateway]
    assigned, used = {}, set()
    if assignments is not None:
        if (set(assignments) != set(desired) or len(set(assignments.values())) != len(assignments)
                or any(address not in available for address in assignments.values())):
            raise GatewayError('gateway_invalid_leases')
        assigned = {public: (address,) for public, address in assignments.items()}
        used = set(assignments.values())
    for public in sorted(desired):
        if public in assigned:
            continue
        routes = observed.get(public, ())
        if len(routes) == 1 and routes[0] in available and routes[0] not in used:
            assigned[public] = routes
            used.add(routes[0])
    for public in sorted(desired, key=desired.get):
        if public not in assigned:
            address = next((ip for ip in available if ip not in used), None)
            if address is None:
                raise GatewayError('gateway_address_pool_exhausted')
            assigned[public] = (address,); used.add(address)
    changed = 0
    try:
        for public, routes in observed.items():
            if public not in assigned or routes != assigned[public]:
                _current(snapshot, policy, int(clock()))
                backend.remove(public); changed += 1
        for public, routes in assigned.items():
            if observed.get(public) != routes:
                _current(snapshot, policy, int(clock()))
                backend.set_peer(public, routes[0]); changed += 1
        backend.verify_scope(policy)
        actual = backend.peers()
        _current(snapshot, policy, int(clock()))
        if actual != assigned:
            raise GatewayError('gateway_readback_mismatch')
    except Exception:
        # Partial application is not approval. Fail closed on the owned interface
        # when it remains reachable and its namespace/key/ownership still match.
        try:
            backend.verify_scope(policy)
            for public in backend.peers():
                backend.remove(public)
        except Exception:
            pass  # Caller must report failure and retry; never claim removal.
        raise GatewayError('gateway_reconciliation_failed') from None
    return {'configuration_observed': True, 'handshake_verified': False, 'changed_operations': changed,
            'server_id': policy.server_id, 'peers': [{'device_id': desired[public], 'public_key': public,
                                                     'address': routes[0]} for public, routes in sorted(actual.items())]}


def clear_owned(policy, backend):
    """Confirm removal only if identity/scope still match and readback is empty."""
    backend.verify_scope(policy)
    for public in backend.peers():
        backend.remove(public)
    backend.verify_scope(policy)
    if backend.peers():
        raise GatewayError('gateway_cleanup_unconfirmed')


class KernelWireGuard:
    """Fixed command vocabulary inside a caller-owned, isolated Linux namespace.

    execute(*argv) must return CompletedProcess[bytes] and enforce a timeout. It
    is a local dependency, never an HTTP parameter. The interface must already be
    UP, with its public key, exact gateway /32 and explicit NOVA ownership alias.
    """
    def __init__(self, execute, interface):
        if sys.platform != 'linux':
            raise GatewayError('linux_namespace_required')
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,14}', interface):
            raise GatewayError('invalid_gateway_interface')
        self.execute, self.interface = execute, interface

    def _run(self, *argv):
        result = self.execute(*argv)
        if result.returncode or not isinstance(result.stdout, bytes) or len(result.stdout) > 65536:
            raise GatewayError('gateway_command_failed')
        return result.stdout.decode('ascii').strip()

    def verify_scope(self, policy):
        inside = self._run('readlink', '/proc/self/ns/net')
        if not re.fullmatch(r'net:\[\d+\]', inside) or inside == os.readlink('/proc/self/ns/net'):
            raise GatewayError('isolated_network_namespace_required')
        links = json.loads(self._run('ip', '-j', '-d', 'link', 'show', 'dev', self.interface))
        if (len(links) != 1 or links[0].get('ifalias') != 'nova-wireguard-v1:'+policy.server_id
                or links[0].get('linkinfo', {}).get('info_kind') != 'wireguard' or 'UP' not in links[0].get('flags', [])):
            raise GatewayError('gateway_interface_not_owned')
        if self._run('wg', 'show', self.interface, 'public-key') != policy.public_key:
            raise GatewayError('gateway_identity_changed')
        addresses = json.loads(self._run('ip', '-j', '-4', 'addr', 'show', 'dev', self.interface))
        actual = {(a['local'], a['prefixlen']) for link in addresses for a in link.get('addr_info', [])}
        if actual != {(policy.gateway, 32)}:
            raise GatewayError('gateway_address_changed')

    @staticmethod
    def _key(public):
        try:
            raw = base64.b64decode(public, validate=True)
            if len(raw) == 32 and base64.b64encode(raw).decode() == public:
                return public
        except (ValueError, TypeError):
            pass
        raise GatewayError('invalid_observed_peer')

    def peers(self):
        result = {}
        for line in self._run('wg', 'show', self.interface, 'allowed-ips').splitlines():
            public, raw = line.split(maxsplit=1)
            self._key(public)
            result[public] = () if raw == '(none)' else tuple(raw.split())
        return result

    def remove(self, public):
        self._run('wg', 'set', self.interface, 'peer', self._key(public), 'remove')

    def set_peer(self, public, address):
        validate_public_key(public)
        route = ipaddress.IPv4Network(address)
        if route.prefixlen != 32 or str(route) != address:
            raise GatewayError('host_route_required')
        self._run('wg', 'set', self.interface, 'peer', public, 'allowed-ips', address)
