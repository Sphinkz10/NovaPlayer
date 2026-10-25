"""Versioned, domain-separated Ed25519 registration proof; not a media token."""
import base64
import ipaddress
import json
import re
import time
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, field_validator

from nova_server.device_api import Payload

DOMAIN = b'NOVA-DIRECTORY-REGISTRATION-v1\n'
ID = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
USERNAME = r'^[a-z][a-z0-9_.-]{2,39}$'
LEASE = 3600


def encode(raw):
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def decode(value, size):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('Invalid encoded proof')
    raw = base64.b64decode(value+'='*((-len(value)) % 4), altchars=b'-_', validate=True)
    if len(raw) != size or encode(raw) != value:
        raise ValueError('Invalid encoded proof')
    return raw


def private_origin(value):
    url = urlsplit(value)
    ip = ipaddress.IPv4Address(url.hostname)
    networks = ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','100.64.0.0/10','127.0.0.1/32')
    if (url.scheme != 'https' or url.port is None or not 1 <= url.port <= 65535 or
            value != f'https://{ip}:{url.port}' or
            not any(ip in ipaddress.ip_network(net) for net in networks)):
        raise ValueError('Private canonical HTTPS IPv4 origin required')
    return value


class Descriptor(Payload):
    schema_version: Literal[1] = 1
    server_id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=64)
    client_origin: str = Field(max_length=100)
    certificate_pem: str = Field(min_length=100, max_length=6000)

    @field_validator('name')
    @classmethod
    def visible(cls, value):
        if not value.strip() or not value.isprintable():
            raise ValueError('Invalid name')
        return value.strip()

    @field_validator('client_origin')
    @classmethod
    def origin(cls, value):
        return private_origin(value)

    @field_validator('certificate_pem')
    @classmethod
    def public_certificate(cls, value):
        if not re.fullmatch(r'-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*', value):
            raise ValueError('One public certificate required')
        x509.load_pem_x509_certificate(value.encode('ascii'))
        return value

    def check_certificate(self, now):
        cert = x509.load_pem_x509_certificate(self.certificate_pem.encode('ascii'))
        moment = datetime.fromtimestamp(now, timezone.utc)
        if not cert.not_valid_before_utc <= moment < cert.not_valid_after_utc:
            raise ValueError('Certificate expired or not yet valid')
        host = ipaddress.ip_address(urlsplit(self.client_origin).hostname)
        try:
            names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
        except x509.ExtensionNotFound:
            raise ValueError('Certificate SAN required') from None
        if host not in names:
            raise ValueError('Certificate hostname mismatch')


class ChallengeRequest(Payload):
    public_key: str = Field(min_length=43, max_length=43)
    descriptor: Descriptor

    @field_validator('public_key')
    @classmethod
    def key(cls, value):
        Ed25519PublicKey.from_public_bytes(decode(value, 32))
        return value


class Proof(Payload):
    challenge_id: str = Field(pattern=ID)
    signature: str = Field(min_length=86, max_length=86)


def message(payload):
    return DOMAIN + json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def validate_payload(p, audience, *, now=None, expected_key=None):
    now = int(time.time() if now is None else now)
    fields = {'purpose','audience','owner_id','entry_id','challenge_id','nonce','public_key',
              'descriptor','version','issued_at','proof_expires_at','expires_at'}
    if not isinstance(p, dict) or set(p) != fields or p['purpose'] != 'register-v1' or p['audience'] != audience:
        raise ValueError('Invalid audience or protocol')
    for name in ('owner_id','entry_id','challenge_id'):
        if not isinstance(p[name], str) or not re.fullmatch(ID, p[name]):
            raise ValueError('Invalid identity')
    for name in ('version','issued_at','proof_expires_at','expires_at'):
        if type(p[name]) is not int:
            raise ValueError('Invalid lifetime')
    if (p['version'] < 1 or p['issued_at'] > now+5 or p['proof_expires_at'] != p['issued_at']+60 or
            p['expires_at'] != p['issued_at']+LEASE or now >= p['expires_at']):
        raise ValueError('Invalid lifetime')
    decode(p['nonce'], 32)
    key = p['public_key']
    if expected_key is not None and key != expected_key:
        raise ValueError('Server key changed')
    Ed25519PublicKey.from_public_bytes(decode(key, 32))
    descriptor = Descriptor.model_validate(p['descriptor'])
    descriptor.check_certificate(now)
    return descriptor


def verify_record(record, audience, *, now=None, expected_key=None):
    """Checks integrity/expiry, not account entitlement. Fetch via authenticated TLS.

    Supply a previously pinned key for continuity. Directory authentication is
    the trust root for first lookup; this is not key transparency.
    """
    if not isinstance(record, dict) or set(record) != {'payload','signature'}:
        raise ValueError('Invalid record')
    p = record['payload']
    descriptor = validate_payload(p, audience, now=now, expected_key=expected_key)
    Ed25519PublicKey.from_public_bytes(decode(p['public_key'], 32)).verify(decode(record['signature'], 64), message(p))
    return descriptor
