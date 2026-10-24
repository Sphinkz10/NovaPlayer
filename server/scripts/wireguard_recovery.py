"""Offline WireGuard identity checks; volatile authorizations are never restored."""
import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from nova_server.wireguard_gateway import GatewayPolicy
from nova_server.gateway_container import KernelLeaseGate
from scripts.wireguard_install import endpoint


def is_wireguard(state):
    state=Path(state)
    return any((state/p).exists() or (state/p).is_symlink() for p in
        ('gateway','identity/gateway','identity/client/wireguard-public.json',
         'identity/admin/channel.key','identity/client/channel.key'))


def validate_gateway_identity(state):
    from scripts.lan_recovery import read_json
    state=Path(state);identity=state/'identity'
    config=read_json(identity/'gateway/gateway.json')
    if (set(config)!={'schema_version','policy','client_port','listen_port'} or
        type(config['schema_version']) is not int or config['schema_version']!=1):
        raise ValueError('Configuração WireGuard inválida.')
    policy=GatewayPolicy(**config['policy'])
    KernelLeaseGate(policy,config['client_port'],config['listen_port'])
    deployment=read_json(identity/'client/deployment.json')
    if config['client_port']!=deployment['ports']['client'] or config['listen_port']!=51820:
        raise ValueError('Portas WireGuard diferentes do deployment.')
    def bounded(path,maximum):
        if path.stat().st_size>maximum:raise ValueError('Identidade WireGuard demasiado grande.')
        return path.read_bytes()
    key=bounded(identity/'gateway/wireguard.key',45)
    if len(key)!=45 or not key.endswith(b'\n'):raise ValueError('Chave WireGuard inválida.')
    raw=base64.b64decode(key[:-1],validate=True)
    if base64.b64encode(raw)!=key[:-1]:raise ValueError('Chave WireGuard inválida.')
    public=X25519PrivateKey.from_private_bytes(raw).public_key().public_bytes(
        serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    if base64.b64encode(public).decode()!=policy.public_key:raise ValueError('Identidade WireGuard inconsistente.')
    secrets=[bounded(identity/role/'channel.key',32) for role in ('gateway','admin','client')]
    if len(secrets[0])!=32 or any(s!=secrets[0] for s in secrets):raise ValueError('Canal WireGuard inconsistente.')
    public_config=read_json(identity/'client/wireguard-public.json')
    if (set(public_config)!={'schema_version','policy','endpoint','client_origin'} or
        type(public_config['schema_version']) is not int or public_config['schema_version']!=1 or
        public_config['policy']!=config['policy'] or
        public_config['client_origin']!=f"https://{policy.gateway}:{config['client_port']}"):
        raise ValueError('Perfil público WireGuard inconsistente.')
    endpoint(public_config['endpoint'])
    return policy


def revoke_gateway_runtime(state):
    """Restore only creates this empty runtime; reject any archived runtime state."""
    state=Path(state)
    runtime=state/'gateway'
    if runtime.exists() and any(runtime.rglob('*')):
        raise ValueError('Estado temporário WireGuard não permitido no restauro.')
    for name in ('channel','leases'):(runtime/name).mkdir(mode=0o700,parents=True,exist_ok=True)
    secret=os.urandom(32)
    for role in ('gateway','admin','client'):
        path=state/'identity'/role/'channel.key'
        # Existing validated private channel copies are rotated in the NEW state.
        path.write_bytes(secret);path.chmod(0o600)
