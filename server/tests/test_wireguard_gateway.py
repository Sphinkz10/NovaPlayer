import json
from types import SimpleNamespace
import uuid

import pytest

import nova_server.wireguard_gateway as module
from nova_server.devices import Devices
from nova_server.wireguard import WireGuardEnrollments
from nova_server.wireguard_gateway import GatewayError, GatewayPolicy, KernelWireGuard, reconcile
from test_wireguard_enrollment import lab, key, request, approve, ADMIN, CLIENT


class Backend:
    def __init__(self, peers=None):
        self.state=dict(peers or {}); self.commands=[]; self.fail_set=False; self.lie=False
    def verify_scope(self, policy): pass
    def peers(self): return dict(self.state)
    def remove(self, public):
        self.commands.append(('remove',public));self.state.pop(public,None)
    def set_peer(self, public, address):
        self.commands.append(('set',public,address))
        if self.fail_set: raise RuntimeError('untrusted backend diagnostic')
        if not self.lie:self.state[public]=(address,)


def policy(): return GatewayPolicy(str(uuid.uuid4()),key(),'10.222.0.0/24','10.222.0.1')
def snapshot(config, peers, now=1000):
    return {'schema_version':1,'server_id':config.server_id,'issued_at':now,'expires_at':now+15,
            'peers':[{'device_id':str(uuid.uuid4()),'public_key':public} for public in peers]}


def test_approved_snapshot_owner_only_and_revocation(lab):
    admin,client,devices,_=lab; path='/api/v1/admin/connect/wireguard/plan'
    assert admin.get(path,headers=dict(client.headers)).status_code==401
    assert client.get(path).status_code==404
    item=request(lab)
    assert admin.get(path).json()['peers']==[]
    assert approve(lab,item).status_code==200
    plan=admin.get(path).json()
    assert plan['server_id']==devices.identity() and 0<plan['expires_at']-plan['issued_at']<=15
    assert plan['peers']==[{'device_id':item['device_id'],'public_key':item['public_key']}]
    devices.revoke(item['device_id'])
    assert admin.get(path).json()['peers']==[]


def test_reconcile_removes_unknown_broad_and_ipv6_peers_then_retains_valid_addresses():
    config=policy(); first,second,stale=key(),key(),key()
    desired=snapshot(config,[first,second])
    backend=Backend({first:('10.222.0.42/32',),second:('0.0.0.0/0','::/0'),stale:('10.222.0.5/32',)})
    report=reconcile(desired,config,backend,clock=lambda:1000)
    assert report['configuration_observed'] and not report['handshake_verified']
    assert backend.state=={first:('10.222.0.42/32',),second:('10.222.0.2/32',)}
    assert backend.commands[:2]==[('remove',second),('remove',stale)]
    count=len(backend.commands)
    assert reconcile(desired,config,backend,clock=lambda:1001)['changed_operations']==0
    assert len(backend.commands)==count
    # A fresh adapter process observes existing assignments rather than reallocating.
    restarted=Backend(backend.state)
    assert reconcile(desired,config,restarted,clock=lambda:1002)['changed_operations']==0
    desired['peers']=[]
    assert reconcile(desired,config,backend,clock=lambda:1003)['peers']==[]
    assert backend.state=={}


@pytest.mark.parametrize('change',[{'expires_at':1000},{'issued_at':1001},{'expires_at':1016},
    {'server_id':str(uuid.uuid4())},{'private_key':'sensitive-sentinel'},{'issued_at':True},
    {'peers':[{'device_id':str(uuid.uuid4()),'public_key':'A'*44,'allowed_ips':['0.0.0.0/0']}]}])
def test_bad_or_stale_snapshot_cannot_mutate_gateway(change):
    config=policy();backend=Backend()
    with pytest.raises((GatewayError,ValueError)):
        reconcile({**snapshot(config,[]),**change},config,backend,clock=lambda:1000)
    assert backend.commands==[]


def test_duplicates_and_pool_exhaustion_are_rejected_before_mutation():
    config=policy(); public=key(); data=snapshot(config,[public])
    data['peers']*=2; backend=Backend()
    with pytest.raises(GatewayError):reconcile(data,config,backend,clock=lambda:1000)
    tiny=GatewayPolicy(config.server_id,config.public_key,'10.222.0.0/30','10.222.0.1')
    with pytest.raises(GatewayError):reconcile(snapshot(tiny,[key(),key()]),tiny,backend,clock=lambda:1000)
    assert backend.commands==[]


@pytest.mark.parametrize('failure',['write','readback','expires_during_apply'])
def test_partial_application_is_not_reported_as_success_and_owned_peers_are_cleared(failure):
    config=policy(); stale,public=key(),key(); backend=Backend({stale:('10.222.0.30/32',)})
    backend.fail_set=failure=='write';backend.lie=failure=='readback'
    values=iter([1000,1000,1015]) if failure=='expires_during_apply' else None
    with pytest.raises(GatewayError,match='gateway_reconciliation_failed'):
        reconcile(snapshot(config,[public]),config,backend,clock=(lambda:next(values)) if values else lambda:1000)
    assert backend.state=={}


def test_kernel_adapter_checks_namespace_ownership_identity_address_and_fixed_commands(monkeypatch):
    monkeypatch.setattr(module.sys,'platform','linux');monkeypatch.setattr(module.os,'readlink',lambda path:'net:[1]')
    config=policy(); calls=[]
    replies={('readlink','/proc/self/ns/net'):'net:[2]',
        ('ip','-j','-d','link','show','dev','wg0'):json.dumps([{'ifalias':'nova-wireguard-v1:'+config.server_id,
            'flags':['UP'],'linkinfo':{'info_kind':'wireguard'}}]),
        ('wg','show','wg0','public-key'):config.public_key,
        ('ip','-j','-4','addr','show','dev','wg0'):json.dumps([{'addr_info':[{'local':config.gateway,'prefixlen':32}]}]),
        ('wg','show','wg0','allowed-ips'):''}
    def execute(*args):
        calls.append(args);return SimpleNamespace(returncode=0,stdout=replies.get(args,'').encode())
    backend=KernelWireGuard(execute,'wg0');backend.verify_scope(config)
    public=key();backend.set_peer(public,'10.222.0.2/32');backend.remove(public)
    assert calls[-2:]==[('wg','set','wg0','peer',public,'allowed-ips','10.222.0.2/32'),('wg','set','wg0','peer',public,'remove')]
    for interface in ('-all','wg0;touch bad','../wg0','wg0 x'):
        with pytest.raises(GatewayError):KernelWireGuard(execute,interface)
    replies[('readlink','/proc/self/ns/net')]='net:[1]'
    with pytest.raises(GatewayError):backend.verify_scope(config)
    replies[('readlink','/proc/self/ns/net')]='net:[2]'
    replies[('wg','show','wg0','public-key')]=key()
    with pytest.raises(GatewayError):backend.verify_scope(config)
    replies[('wg','show','wg0','public-key')]=config.public_key
    replies[('ip','-j','-d','link','show','dev','wg0')]='[]'
    with pytest.raises(GatewayError):backend.verify_scope(config)
