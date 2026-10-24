"""Owner-provided public Tailscale setup policy, never a tailnet auth-key broker.

An approved NOVA association may retrieve its own policy. Tailnet membership is
independently granted by its operator. No route, DNS, exit-node or new TLS anchor
can be supplied by a TV. The adapter/installer remains opt-in.
"""
import ipaddress
import json
import re
import time
from urllib.parse import urlsplit

from .devices import Devices
from .gateway_channel import read_private


def control_origin(value):
    if not isinstance(value, str) or len(value)>270:
        raise ValueError('Invalid control origin')
    parsed=urlsplit(value)
    host=parsed.hostname or ''
    if (parsed.scheme!='https' or not host or len(host)>253 or
            not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in host.split('.')) or
            parsed.port is not None and not 1<=parsed.port<=65535 or
            value!='https://'+host+(':'+str(parsed.port) if parsed.port is not None else '')):
        raise ValueError('Invalid control origin')
    return value


def gateway_origin(value):
    if not isinstance(value,str):raise ValueError('Invalid gateway origin')
    parsed=urlsplit(value)
    host=ipaddress.IPv4Address(parsed.hostname or '')
    if (host not in ipaddress.IPv4Network('100.64.0.0/10') or parsed.scheme!='https' or
            parsed.port is None or not 1024<=parsed.port<=65535 or value!=f'https://{host}:{parsed.port}'):
        raise ValueError('Invalid gateway origin')
    return value


class TailscaleProfiles:
    def __init__(self,store,config,base_origin,*,clock=time.time,approval=None):
        from .lan import lan_ip
        parsed=urlsplit(base_origin)
        # Policy is anchored in an existing LAN identity; never accept a remote
        # origin as a bootstrap certificate/identity authority.
        lan_ip(parsed.hostname or '')
        if parsed.port is None or base_origin!=f'https://{parsed.hostname}:{parsed.port}':
            raise ValueError('Exact LAN HTTPS origin required')
        if (not isinstance(config,dict) or set(config)!={'schema_version','server_id','revision','control_origin','client_origin'} or
                type(config['schema_version']) is not int or config['schema_version']!=1 or
                type(config['revision']) is not int or config['revision']<1 or config['revision']>2147483647 or
                config['server_id']!=Devices(store).identity()):
            raise ValueError('Invalid Tailscale public policy')
        self.control=control_origin(config['control_origin'])
        self.origin=gateway_origin(config['client_origin'])
        self.revision=config['revision']
        self.base_origin,self.devices,self.clock=base_origin,Devices(store,clock=clock),clock
        self.approval=approval

    @classmethod
    def local(cls,store,path,base_origin):
        return cls(store,json.loads(read_private(path,8192)),base_origin)

    def issue(self,access):
        device=self.devices.authenticate(access)
        revision=self.approval.authorization() if self.approval else self.revision
        now=int(self.clock())
        return {'schema_version':1,'provider':'tailscale','server_id':device['server_id'],
                'device_id':device['device_id'],'account_id':device['account_id'],
                'base_origin':self.base_origin,'control_origin':self.control,'client_origin':self.origin,
                'revision':revision,'issued_at':now,'expires_at':now+86400}
