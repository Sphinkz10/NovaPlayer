"""Explicit private-LAN deployment contract. Legacy loopback launchers stay opt-in."""
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

NETWORKS = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))


def lan_ip(value):
    ip=ipaddress.IPv4Address(value)
    if str(ip)!=value or not any(ip in network for network in NETWORKS):
        raise ValueError('Indica um IPv4 privado da LAN (10.x, 172.16–31.x ou 192.168.x).')
    return str(ip)


def validate(config):
    if set(config)!={'version','ip','ports','operator_id'} or config['version']!=1:
        raise ValueError('Unsupported LAN deployment')
    lan_ip(config['ip'])
    ports=config['ports']
    if (set(ports)!={'admin','client','directory'} or any(type(p) is not int or not 1024<=p<=65535 for p in ports.values())
            or len(set(ports.values()))!=3):
        raise ValueError('Three distinct non-privileged TLS ports required')
    import uuid
    if str(uuid.UUID(config['operator_id']))!=config['operator_id']:raise ValueError('Invalid operator')
    return config


def load(path):
    path=Path(path)
    if path.stat().st_size>4096:raise ValueError('Invalid deployment file')
    return validate(json.loads(path.read_text(encoding='utf8')))


def origin(config,role):
    return f"https://{config['ip']}:{config['ports'][role]}"


def validate_leaf(path,ip):
    from cryptography import x509
    from datetime import datetime,timezone
    cert=x509.load_pem_x509_certificate(Path(path).read_bytes())
    names=cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    if ipaddress.ip_address(ip) not in names.get_values_for_type(x509.IPAddress):raise ValueError('TLS SAN mismatch')
    if not cert.not_valid_before_utc<=datetime.now(timezone.utc)<cert.not_valid_after_utc:raise ValueError('TLS expired')
    return cert
