"""Owner approval of an explicitly prepared public Tailscale policy.

No tailnet secret, daemon command or new certificate is accepted over HTTP.
Approval means permission to provision the profile, never observed connectivity.
"""
from datetime import datetime,timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import stat

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from pydantic import ConfigDict,Field

from .device_api import Payload
from .devices import DeviceError
from .gateway_channel import canonical,read_private
from .tailscale_profile import TailscaleProfiles


class TailscaleDecision(Payload):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=1,le=2147483647)
    approve:bool
    policy_digest:str=Field(pattern=r'^[a-f0-9]{64}$')


def public_leaf(path):
    path=Path(path)
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 128<=info.st_size<=16384:
        raise ValueError('Prepared public certificate required')
    with path.open('rb') as source:
        raw=source.read(16385)
    if len(raw)>16384:raise ValueError('Prepared public certificate required')
    return x509.load_pem_x509_certificate(raw)


class TailscaleControl:
    def __init__(self,store,configuration,base_origin,certificate):
        # Reuse exactly the device profile's parser; no weaker admin-side form.
        policy=TailscaleProfiles(store,configuration,base_origin)
        self.store,self.policy=store,policy
        self.leaf=public_leaf(certificate)
        self._valid_leaf()
        self.fingerprint=hashlib.sha256(self.leaf.public_bytes(serialization.Encoding.DER)).hexdigest()
        self.digest=hashlib.sha256(canonical({'policy':configuration,'base_origin':base_origin,
                                            'certificate_sha256':self.fingerprint})).hexdigest()

    def _valid_leaf(self):
        from urllib.parse import urlsplit
        now=datetime.now(timezone.utc)
        names=self.leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        addresses=names.get_values_for_type(x509.IPAddress)
        if (self.leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca or
                not self.leaf.not_valid_before_utc<=now<self.leaf.not_valid_after_utc or
                any(ipaddress.ip_address(urlsplit(origin).hostname) not in addresses
                    for origin in (self.policy.base_origin,self.policy.origin))):
            raise ValueError('Certificate must cover LAN and Tailscale gateway')

    @classmethod
    def local(cls,store,configuration,base_origin,certificate):
        return cls(store,json.loads(read_private(configuration,8192)),base_origin,certificate)

    @staticmethod
    def options():
        value=os.environ.get('NOVA_TAILSCALE_MANAGED')
        if value is None:return None
        if value!='1':raise ValueError('NOVA_TAILSCALE_MANAGED must be exactly 1 when configured')
        return {'configuration':os.environ['NOVA_TAILSCALE_PUBLIC_CONFIG'],
                'base_origin':os.environ['NOVA_TAILSCALE_BASE_ORIGIN'],
                'certificate':os.environ['NOVA_TAILSCALE_CERTIFICATE_FILE']}

    def _state(self,db):
        row=db.execute('SELECT policy_digest,approved,revision FROM tailscale_approval WHERE id=1').fetchone()
        # A changed policy/certificate never inherits approval. Keep the revision
        # increasing across replacements so an old browser cannot approve it.
        if not row:return False,1
        return bool(row[1]) if row[0]==self.digest else False,row[2]

    def status(self):
        try:self._valid_leaf()
        except ValueError:raise DeviceError('tailscale_certificate_unavailable',503) from None
        with self.store._db() as db:approved,revision=self._state(db)
        return {'schema_version':1,'state':'approved' if approved else 'approval_required',
            'profile_approved':approved,'revision':revision,'policy_digest':self.digest,'server_id':self.policy.devices.identity(),
            'control_origin':self.policy.control,'base_origin':self.policy.base_origin,
            'client_origin':self.policy.origin,'certificate_sha256':self.fingerprint,
            'gateway_verified':False,'remote_access_enabled':False}

    def decide(self,revision,approve,policy_digest):
        self._valid_leaf()
        with self.store._db() as db:
            db.execute('BEGIN IMMEDIATE')
            approved,current=self._state(db)
            if revision!=current or policy_digest!=self.digest:raise DeviceError('tailscale_approval_changed',409)
            if current>=2147483647:raise DeviceError('tailscale_revision_exhausted',409)
            db.execute('INSERT INTO tailscale_approval VALUES(1,?,?,?,strftime(\'%s\',\'now\')) '
                'ON CONFLICT(id) DO UPDATE SET policy_digest=excluded.policy_digest,approved=excluded.approved,'
                'revision=excluded.revision,updated_at=excluded.updated_at',(self.digest,int(approve),current+1))
            db.execute('INSERT INTO audit(event,created_at) VALUES(?,strftime(\'%s\',\'now\'))',
                       ('tailscale.profile_approved' if approve else 'tailscale.profile_disabled',))
        return self.status()

    def authorization(self):
        state=self.status()
        if not state['profile_approved']:raise DeviceError('tailscale_owner_approval_required',403)
        return state['revision']
