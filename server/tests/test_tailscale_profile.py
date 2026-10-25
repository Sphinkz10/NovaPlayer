import json
import time

import pytest
from fastapi.testclient import TestClient

from nova_server.client_api import make_client_app
from nova_server.devices import Devices
from nova_server.storage import Store
from nova_server.tailscale_profile import TailscaleProfiles, control_origin, gateway_origin

LAN='https://10.1.0.1:9444'
REMOTE='https://100.64.0.1:9444'
PATH='/api/v1/device/tailscale/profile'


@pytest.fixture
def policy(tmp_path):
    store=Store(tmp_path);store.bootstrap('owner','unused')
    devices=Devices(store)
    grant=devices.start('TV')
    devices.decide(grant['user_code'],devices.inspect(grant['user_code'])['request_id'],True)
    tokens=devices.poll(grant['device_code'])
    config={'schema_version':1,'server_id':devices.identity(),'revision':1,
            'control_origin':'https://controlplane.tailscale.com','client_origin':REMOTE}
    return store,devices,tokens,config


def test_authenticated_profile_and_descriptor_keep_exact_identity(policy):
    store,devices,tokens,config=policy
    profiles=TailscaleProfiles(store,config,LAN)
    with TestClient(make_client_app(store.dir,LAN,tailscale_profiles=profiles),base_url=LAN) as client:
        client.headers['Authorization']='Bearer '+tokens['access_token']
        result=client.get(PATH);assert result.status_code==200
        data=result.json()
        assert set(data)=={'schema_version','provider','server_id','device_id','account_id','base_origin',
                           'control_origin','client_origin','revision','issued_at','expires_at'}
        assert data['server_id']==devices.identity() and data['device_id']==tokens['device_id']
        assert data['base_origin']==LAN and data['client_origin']==REMOTE
        assert data['expires_at']-data['issued_at']==86400
        assert result.headers['Cache-Control']=='no-store'
        assert client.get('/api/v1/device/me').json()['descriptor']['client_origin']==LAN
        remote=client.get(REMOTE+'/api/v1/device/me')
        assert remote.status_code==200 and remote.json()['descriptor']['client_origin']==REMOTE
        assert remote.json()['descriptor']['remote_access_enabled'] is False
        assert client.get('https://100.64.0.2:9444/api/v1/device/me').status_code==400
        assert client.get(REMOTE+'/api/v1/admin/connect').status_code==404
        assert client.post(PATH,json={'auth_key':'secret-sentinel'}).status_code==405
        devices.revoke(tokens['device_id'])
        assert client.get(PATH).status_code==401


def test_disabled_provider_and_credentials_are_not_interchangeable(policy):
    store,_,tokens,config=policy
    with TestClient(make_client_app(store.dir,LAN),base_url=LAN) as client:
        assert client.get(PATH).status_code==401
        client.headers['Authorization']='Bearer '+tokens['access_token']
        assert client.get(PATH).status_code==503
    owner='o'*48;store.save_session(owner)
    with TestClient(make_client_app(store.dir,LAN,tailscale_profiles=TailscaleProfiles(store,config,LAN)),base_url=LAN) as client:
        assert client.get(PATH,headers={'Authorization':'Bearer '+owner}).status_code==401
        assert client.get(PATH,headers={'Authorization':'Bearer '+tokens['refresh_token']}).status_code==401


@pytest.mark.parametrize('value',[
    'http://100.64.0.1:9444','https://100.63.255.255:9444','https://100.128.0.0:9444',
    'https://10.0.0.1:9444','https://example.com:9444','https://100.064.0.1:9444',
    'https://100.64.0.1','https://100.64.0.1:443','https://100.64.0.1:09444',
    'https://user@100.64.0.1:9444','https://100.64.0.1:9444/','https://100.64.0.1:9444?x=1',
    'https://100.64.0.1:9444#x',None,
])
def test_gateway_policy_never_accepts_routes_dns_or_noncanonical_origins(value):
    with pytest.raises((ValueError,TypeError)):gateway_origin(value)


@pytest.mark.parametrize('value',[
    'http://control.example','https://user@control.example','https://control.example/',
    'https://control.example?key=secret','https://control.example#x','https://CONTROL.example',
    'https://control.example:0443','https://control.example:0','https://control.example:65536',
    'https://-bad.example','https://control.example\n',None,
])
def test_control_origin_rejects_ambiguous_input(value):
    with pytest.raises((ValueError,TypeError)):control_origin(value)


@pytest.mark.parametrize('change',[
    {'auth_key':'secret-sentinel'},{'routes':['0.0.0.0/0']},{'certificate_pem':'secret-sentinel'},
    {'schema_version':True},{'revision':True},{'revision':0},{'revision':2147483648},
    {'server_id':'other-server'},
])
def test_no_extra_secrets_routes_certificates_or_wrong_server(policy,change):
    store,_,_,config=policy
    with pytest.raises(ValueError):TailscaleProfiles(store,{**config,**change},LAN)


def test_member_disabled_and_expired_credentials_refuse_profiles(policy):
    store,_,tokens,config=policy
    profiles=TailscaleProfiles(store,config,LAN)
    assert profiles.issue(tokens['access_token'])['account_id'] is None
    with store._db() as db:
        db.execute("INSERT INTO member_accounts(subject,username,disabled) VALUES('member','alice',1)")
        db.execute("UPDATE devices SET account_id='member' WHERE id=?",(tokens['device_id'],))
    from nova_server.devices import DeviceError
    with pytest.raises(DeviceError):profiles.issue(tokens['access_token'])


def test_opt_in_file_is_private_server_bound_and_loaded_at_start(policy,monkeypatch,tmp_path):
    store,_,tokens,config=policy
    path=tmp_path/'public.json';path.write_text(json.dumps(config));path.chmod(0o600)
    monkeypatch.setenv('NOVA_TAILSCALE_PUBLIC_CONFIG',str(path))
    with TestClient(make_client_app(store.dir,LAN),base_url=LAN) as client:
        assert client.get(PATH,headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==200
    config['server_id']='wrong';path.write_text(json.dumps(config))
    with pytest.raises(ValueError):make_client_app(store.dir,LAN)
