import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nova_server.client_api import make_client_app
from nova_server.devices import DeviceError
from nova_server.gateway_channel import GatewayChannel, GatewayPublisher, atomic_private
from nova_server.gateway_container import KernelLeaseGate
from nova_server.gateway_service import DurableLeases, GatewayWorker
from nova_server.wireguard import WireGuardEnrollments
from nova_server.wireguard_gateway import GatewayError, GatewayPolicy
from nova_server.wireguard_profile import WireGuardProfiles
from scripts.wireguard_install import prepare, endpoint
from test_wireguard_gateway import Backend, policy
from test_wireguard_enrollment import lab, request, approve, key, associate


def test_kernel_gate_expires_established_traffic_and_only_opens_exact_https():
    calls=[]
    def run(*args,**kwargs):
        calls.append((args,kwargs))
        return SimpleNamespace(returncode=1 if args[:2]==('nft','list') else 0,stdout=b'')
    gate=KernelLeaseGate(policy(),8920,51820,run);gate.install()
    rules=calls[-1][1]['data'].decode()
    assert rules.index('iifname "wg0" drop')<rules.index('ct state established,related accept')
    assert 'ip saddr @live tcp dport 8920 accept' in rules
    assert 'ip daddr @live tcp sport 8920 accept' in rules
    assert 'hook forward priority -50; policy drop' in rules
    assert 'flush ruleset' not in rules
    gate.authorize([{'address':'10.222.0.2/32'}],14.5)
    assert b'10.222.0.2 timeout 12500ms' in calls[-1][1]['data']
    gate.close();assert calls[-1][1]['data']==b'flush set inet nova_gateway live\n'
    for address in ('0.0.0.0/0','10.222.0.1/32','10.222.0.0/32','10.222.0.255/32','192.168.1.2/32'):
        with pytest.raises((ValueError,GatewayError)):gate.authorize([{'address':address}],10)
    for ttl in (-1,0,2,16,float('nan'),float('inf')):
        with pytest.raises(GatewayError):gate.authorize([],ttl)


@pytest.mark.parametrize('value',['example.com:51820\nPostUp=x','https://example.com:51820','x:0','x:65536','x:01','a..b:22','256.1.1.1:1234','a;id:1234'])
def test_underlay_endpoint_rejects_injection(value):
    with pytest.raises(ValueError):endpoint(value)


@pytest.fixture
def remote(lab,tmp_path):
    admin,client,service,tokens=lab
    item=request(lab);assert approve(lab,item).status_code==200
    enrollments=WireGuardEnrollments(service.store)
    p=GatewayPolicy(enrollments.gateway_plan()['server_id'],key(),'10.222.0.0/24','10.222.0.1')
    folder=tmp_path/'channel';folder.mkdir(mode=0o700)
    leases=tmp_path/'leases';leases.mkdir(mode=0o700)
    secret=tmp_path/'channel.key';atomic_private(secret,os.urandom(32))
    channel=GatewayChannel(folder,secret);publisher=GatewayPublisher(enrollments,channel)
    publisher.publish()
    worker=GatewayWorker(p,Backend(),channel,DurableLeases(leases,p));assert worker.tick()
    config={'schema_version':1,'policy':p.__dict__,'endpoint':'vpn.example.org:51820','client_origin':'https://10.222.0.1:8920'}
    profiles=WireGuardProfiles(service.store,config,channel)
    return profiles,worker,publisher,tokens,service


def test_public_profile_bound_to_device_fresh_observation_and_revocation(remote):
    profiles,worker,publisher,tokens,service=remote
    result=profiles.issue(tokens['access_token'])
    assert result['device_id']==tokens['device_id'] and result['address']=='10.222.0.2/32'
    assert result['allowed_ip']=='10.222.0.1/32' and result['handshake_verified'] is False
    assert result['expires_at']-result['issued_at']==86400
    assert 'private' not in json.dumps(result).lower()
    other=associate(service)
    with pytest.raises(DeviceError):profiles.issue(other['access_token'])
    service.revoke(tokens['device_id'])
    with pytest.raises(DeviceError) as error:profiles.issue(tokens['access_token'])
    assert error.value.status==401


def test_public_profile_fails_closed_if_worker_unavailable(remote):
    profiles,worker,publisher,tokens,_=remote
    worker.stop()
    with pytest.raises(DeviceError) as error:profiles.issue(tokens['access_token'])
    assert error.value.status==503
    assert worker.tick()
    publisher.channel.directory.joinpath('plan.json').unlink()
    with pytest.raises(DeviceError):profiles.issue(tokens['access_token'])


def test_profile_route_and_origin_are_authenticated_without_admin_surface(remote):
    profiles,_,_,tokens,service=remote
    app=make_client_app(service.store.dir,'https://192.168.1.2:8920',wireguard_profiles=profiles)
    with TestClient(app,base_url=profiles.origin) as client:
        assert client.get('/api/v1/device/wireguard/profile').status_code==401
        client.headers['Authorization']='Bearer '+tokens['access_token']
        assert client.get('/api/v1/device/wireguard/profile').status_code==200
        assert client.get('/api/v1/device/me').json()['descriptor']['client_origin']==profiles.origin
        assert client.get('/api/v1/admin/overview').status_code==404
        assert client.get('/api/v1/device/me',headers={'Host':'10.222.0.99'}).status_code==400


def test_installer_provisions_only_dedicated_gateway_mounts_and_capabilities(tmp_path):
    output=tmp_path/'new'
    prepare(output,gateway_image='ghcr.io/sphinkz10/nova-gateway@sha256:'+'b'*64,udp_endpoint='vpn.example.org:51820',
        ip='192.168.1.2',state_root='/mnt/pool/nova',media_a='/mnt/pool/a',media_b='/mnt/pool/b',uid=10001,gid=10001,
        image='ghcr.io/sphinkz10/nova-core@sha256:'+'a'*64,version='25.10.5',username='owner',password='test-private-owner-passphrase')
    compose=json.loads((output/'instalar-no-truenas.yaml').read_text())
    services=compose['services'];gateway=services['nova-gateway']
    assert gateway['cap_add']==['NET_ADMIN','DAC_OVERRIDE','CHOWN']
    assert gateway['sysctls']['net.ipv4.ip_forward']=='0'
    assert all('privileged' not in item and item.get('network_mode')!='host' for item in services.values())
    assert all(not item.get('cap_add') for name,item in services.items() if name!='nova-gateway')
    assert set(mount['target'] for mount in gateway['volumes'])=={'/identity','/channel','/leases'}
    assert all('/mnt/pool/nova/nova'!=mount['source'] and 'docker.sock' not in str(mount) for mount in gateway['volumes'])
    assert services['nova-client']['network_mode']=='service:nova-gateway' and 'ports' not in services['nova-client']
    assert '192.168.1.2:51820:51820/udp' in gateway['ports']
    assert not (output/'copiar-para-nas/identity/client/wireguard.key').exists()
    from cryptography import x509
    cert=x509.load_pem_x509_certificate((output/'copiar-para-nas/identity/client/server.crt').read_bytes())
    hosts=cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
    assert set(map(str,hosts))=={'192.168.1.2','10.222.0.1'}
