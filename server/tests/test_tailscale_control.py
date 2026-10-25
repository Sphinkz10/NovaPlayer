from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import shutil
import sqlite3
import tarfile
from contextlib import closing

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from test_lan import deployment
from test_wireguard_enrollment import associate
from test_recovery import state_fixture
from nova_server.app import make_app
from nova_server.client_api import make_client_app
from nova_server.devices import Devices,DeviceError
from nova_server.storage import Store
from nova_server.tailscale_control import TailscaleControl
from scripts.tailscale_prepare import prepare as prepare_profile
from scripts.lan_recovery import validate_lan,deployment_values
from scripts.recovery import revoke_restored_sessions,files_for_backup,extract_checked

ADMIN='/api/v1/admin/connect/tailscale'
PROFILE='/api/v1/device/tailscale/profile'

def prepare(*args,**kwargs):
    return prepare_profile(*args,image='ghcr.io/sphinkz10/nova-core@sha256:'+'b'*64,**kwargs)


def apply_patch(folder,patch):
    for path in (patch/'copiar-para-nas').rglob('*'):
        if path.is_file():shutil.copy2(path,folder/'copiar-para-nas'/path.relative_to(patch/'copiar-para-nas'))
    shutil.copyfile(patch/'instalar-no-truenas.yaml',folder/'instalar-no-truenas.yaml')


@pytest.fixture
def prepared(deployment,tmp_path):
    folder,info=deployment
    old_cert=(folder/'copiar-para-nas/identity/client/server.crt').read_bytes()
    keys={path:path.read_bytes() for path in folder.rglob('*.key')}
    patch=tmp_path/'patch'
    report=prepare(folder,patch,gateway='100.64.0.1')
    assert (folder/'copiar-para-nas/identity/client/server.crt').read_bytes()==old_cert
    assert all(path.read_bytes()==value for path,value in keys.items())
    assert not list(patch.rglob('*.key')) and not list(patch.rglob('*.sqlite3'))
    apply_patch(folder,patch)
    state=folder/'copiar-para-nas';store=Store(state/'nova')
    options={'configuration':state/'identity/admin/tailscale-public.json','base_origin':info['client'],
             'certificate':state/'identity/admin/client.crt'}
    return folder,info,store,options,report


def decision(client,state,approve=True):
    return client.post(ADMIN,json={'revision':state['revision'],'policy_digest':state['policy_digest'],'approve':approve})


def test_offline_preparation_preserves_private_identity_expiry_and_recovery_contract(prepared):
    folder,info,store,options,report=prepared;state=folder/'copiar-para-nas'
    leaf=x509.load_pem_x509_certificate((state/'identity/client/server.crt').read_bytes())
    key=serialization.load_pem_private_key((state/'identity/client/server.key').read_bytes(),password=None)
    assert key.public_key().public_numbers()==leaf.public_key().public_numbers()
    assert str(leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)[1])=='100.64.0.1'
    assert validate_lan(state)['server_id']==report['server_id']
    values=deployment_values(state,(folder/'instalar-no-truenas.yaml').read_text(encoding='utf8'))
    assert values['state_root']=='/mnt/pool/nova'
    data=json.loads((folder/'instalar-no-truenas.yaml').read_text())
    assert len(data['services'])==4 and not report['gateway_installed']
    for role in ('admin','client'):
        service=data['services']['nova-'+role]
        assert service['environment']['NOVA_TAILSCALE_MANAGED']=='1'
        assert all('100.64' not in value for value in service['ports'])
        assert not any('ca.key' in str(mount) or 'docker.sock' in str(mount) for mount in service['volumes'])


def test_owner_approval_profile_and_disable_preserve_lan_and_role_boundaries(prepared,monkeypatch):
    _,info,store,options,_=prepared
    devices=Devices(store);tokens=associate(devices)
    owner='owner-'+'a'*48;store.save_session(owner)
    monkeypatch.setenv('NOVA_TAILSCALE_MANAGED','1')
    monkeypatch.setenv('NOVA_TAILSCALE_PUBLIC_CONFIG',str(options['configuration']))
    monkeypatch.setenv('NOVA_TAILSCALE_BASE_ORIGIN',info['client'])
    monkeypatch.setenv('NOVA_TAILSCALE_CERTIFICATE_FILE',str(options['certificate']))
    remote='https://100.64.0.1:8920'
    with TestClient(make_app(store.dir,allowed_hosts=['testserver'],tailscale_options=options)) as admin, TestClient(
            make_client_app(store.dir,info['client']),base_url=info['client']) as client:
        assert admin.get(ADMIN).status_code==401
        assert admin.get(ADMIN,headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==401
        admin.headers['Authorization']='Bearer '+owner
        client.headers['Authorization']='Bearer '+tokens['access_token']
        state=admin.get(ADMIN).json()
        assert state['state']=='approval_required' and not state['profile_approved']
        assert not state['gateway_verified'] and not state['remote_access_enabled']
        assert client.get(PROFILE).status_code==403
        assert client.get(remote+'/api/v1/device/me').status_code==403
        assert client.get(remote+'/api/v1/device/me',headers={'Host':'192.168.50.20:8920'}).status_code==403
        assert client.get('/api/v1/device/me').status_code==200
        approved=decision(admin,state);assert approved.status_code==200
        approved=approved.json();assert approved['revision']==2 and approved['profile_approved']
        issued=client.get(PROFILE);assert issued.status_code==200 and issued.json()['revision']==2
        assert issued.json()['device_id']==tokens['device_id'] and issued.headers['Cache-Control']=='no-store'
        assert client.get(remote+'/api/v1/device/me').json()['descriptor']['client_origin']==remote
        assert client.get(remote+ADMIN).status_code==404
        assert client.get(PROFILE,headers={'Authorization':'Bearer '+owner}).status_code==401
        assert decision(admin,state).status_code==409
        disabled=decision(admin,approved,False).json();assert disabled['revision']==3 and not disabled['profile_approved']
        assert client.get(PROFILE).status_code==403 and client.get(remote+'/api/v1/device/me').status_code==403
        assert client.get(remote+'/api/v1/device/me',headers={'Host':'192.168.50.20:8920'}).status_code==403
        assert client.get('/api/v1/device/me').status_code==200
        assert admin.get(ADMIN).json()['gateway_verified'] is False


@pytest.mark.parametrize('extra',[
    {'approve':1},{'revision':True},{'revision':0},{'auth_key':'secret-sentinel'},
    {'certificate_pem':'secret-sentinel'},{'client_origin':'https://8.8.8.8:8920'},
    {'control_origin':'https://other.invalid'},{'routes':['0.0.0.0/0']},{'gateway_verified':True},
])
def test_owner_http_cannot_change_policy_or_submit_secrets(prepared,extra):
    _,_,store,options,_=prepared;owner='o'*48;store.save_session(owner)
    with TestClient(make_app(store.dir,allowed_hosts=['testserver'],tailscale_options=options)) as client:
        client.headers['Authorization']='Bearer '+owner
        state=client.get(ADMIN).json()
        result=client.post(ADMIN,json={'revision':state['revision'],'policy_digest':state['policy_digest'],'approve':True,**extra})
        assert result.status_code==422 and 'secret-sentinel' not in result.text
        assert not client.get(ADMIN).json()['profile_approved']


def test_changed_policy_does_not_inherit_approval_or_accept_old_browser_decision(prepared,tmp_path):
    _,_,store,options,_=prepared
    first=TailscaleControl.local(store,**options);state=first.status()
    first.decide(state['revision'],True,state['policy_digest']);old=first.status()
    config=json.loads(options['configuration'].read_text());config['control_origin']='https://new.example'
    path=tmp_path/'new-policy.json';path.write_text(json.dumps(config));path.chmod(0o600)
    other=TailscaleControl.local(store,**{**options,'configuration':path})
    assert not other.status()['profile_approved']
    with pytest.raises(DeviceError):other.decide(old['revision'],True,old['policy_digest'])
    current=other.status();other.decide(current['revision'],True,current['policy_digest'])
    assert not first.status()['profile_approved'] and other.status()['profile_approved']


def test_reissued_certificate_cannot_reuse_approval_even_with_same_tls_key(deployment,tmp_path):
    folder,info=deployment
    a=tmp_path/'a';b=tmp_path/'b'
    prepare(folder,a,gateway='100.64.0.1');prepare(folder,b,gateway='100.64.0.1')
    store=Store(folder/'copiar-para-nas/nova')
    configuration=a/'copiar-para-nas/identity/admin/tailscale-public.json'
    first=TailscaleControl.local(store,configuration,info['client'],a/'copiar-para-nas/identity/admin/client.crt')
    status=first.status();first.decide(status['revision'],True,status['policy_digest'])
    approved=first.status()
    second=TailscaleControl.local(store,configuration,info['client'],b/'copiar-para-nas/identity/admin/client.crt')
    assert first.leaf.public_key().public_numbers()==second.leaf.public_key().public_numbers()
    assert not second.status()['profile_approved']
    with pytest.raises(DeviceError):second.decide(approved['revision'],True,approved['policy_digest'])


def test_preparer_never_writes_staging_inside_source_installation(deployment):
    folder,_=deployment
    with pytest.raises(ValueError,match='separate new'):prepare(folder,folder/'patch',gateway='100.64.0.1')
    assert not (folder/'patch').exists()


@pytest.mark.parametrize('value',['0','true','false','yes'])
def test_invalid_managed_mode_never_silently_falls_back(monkeypatch,value):
    monkeypatch.setenv('NOVA_TAILSCALE_MANAGED',value)
    with pytest.raises(ValueError):TailscaleControl.options()


def test_concurrent_decisions_allow_only_one_revision(prepared):
    _,_,store,options,_=prepared;control=TailscaleControl.local(store,**options);state=control.status()
    def execute():
        try:return control.decide(state['revision'],True,state['policy_digest'])['revision']
        except DeviceError:return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(lambda _:execute(),range(2)))
    assert sorted(map(str,result))==['2','refused']


@pytest.mark.parametrize('gateway',['192.168.1.2','8.8.8.8','100.63.255.255','100.128.0.1','100.064.0.1','example.com','100.64.0.1/32'])
def test_preparer_rejects_nonoverlay_gateway_before_output(deployment,tmp_path,gateway):
    folder,_=deployment;output=tmp_path/'bad'
    with pytest.raises(ValueError):prepare(folder,output,gateway=gateway)
    assert not output.exists()


def test_preparer_refuses_existing_output_and_associated_installation(deployment,tmp_path):
    folder,_=deployment;output=tmp_path/'existing';output.mkdir();(output/'keep').write_text('keep')
    with pytest.raises(FileExistsError):prepare(folder,output,gateway='100.64.0.1')
    assert (output/'keep').read_text()=='keep'
    store=Store(folder/'copiar-para-nas/nova');associate(Devices(store))
    with pytest.raises(ValueError,match='before associating'):prepare(folder,tmp_path/'other',gateway='100.64.0.1')
    assert not (tmp_path/'other').exists()


def test_snapshot_restore_invalidates_public_profile_approval(tmp_path):
    state_fixture(tmp_path)
    store=Store(tmp_path/'nova')
    with store._db() as db:db.execute("INSERT INTO tailscale_approval VALUES(1,?,1,2,0)",('a'*64,))
    revoke_restored_sessions(tmp_path)
    with store._db() as db:assert db.execute('SELECT approved,revision FROM tailscale_approval').fetchone()==(0,3)


def test_full_recovery_keeps_certificate_and_managed_policy_but_requires_new_approval(prepared,tmp_path):
    folder,info,store,options,_=prepared;state=folder/'copiar-para-nas'
    control=TailscaleControl.local(store,**options);pending=control.status()
    control.decide(pending['revision'],True,pending['policy_digest'])
    jf=state/'jellyfin/config/data';jf.mkdir()
    with closing(sqlite3.connect(jf/'jellyfin.db')) as db,db:
        db.executescript('CREATE TABLE Users(Id TEXT); INSERT INTO Users VALUES("owner");'
            'CREATE TABLE Devices(Id TEXT); CREATE TABLE ApiKeys(Id TEXT);')
    text=(folder/'instalar-no-truenas.yaml').read_text(encoding='utf8')
    _,files=files_for_backup(state)
    assert state/'identity/client/tailscale-public.json' in files
    assert not any('GUARDAR-OFFLINE' in str(file) for file in files)
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as archive:
        manifest=json.dumps({'format':2,'nova_schema':3,'deployment':text}).encode()
        entry=tarfile.TarInfo('manifest.json');entry.size=len(manifest);archive.addfile(entry,io.BytesIO(manifest))
        for file in files:archive.add(file,arcname='state/'+file.relative_to(state).as_posix(),recursive=False)
    staging=tmp_path/'recovered';staging.mkdir();stream.seek(0)
    manifest=extract_checked(stream,staging)
    from scripts.lan_recovery import revoke_lan,write_restored_guidance
    restored=staging/'state'
    revoke_restored_sessions(restored);revoke_lan(restored)
    write_restored_guidance(staging,manifest,state_root='/mnt/pool/recovered',image='ghcr.io/sphinkz10/nova-core@sha256:'+'c'*64)
    renewed=TailscaleControl.local(Store(restored/'nova'),restored/'identity/admin/tailscale-public.json',
                                  info['client'],restored/'identity/admin/client.crt')
    assert renewed.fingerprint==control.fingerprint and not renewed.status()['profile_approved']
    compose=json.loads((staging/'instalar-no-truenas.yaml').read_text())
    for role in ('admin','client'):
        assert compose['services']['nova-'+role]['environment']['NOVA_TAILSCALE_MANAGED']=='1'
        assert compose['services']['nova-'+role]['image'].endswith('c'*64)


def test_unprepared_server_never_activates_tailscale(tmp_path):
    store=Store(tmp_path);store.bootstrap('owner','unused');owner='o'*48;store.save_session(owner)
    with TestClient(make_app(store.dir,allowed_hosts=['testserver'])) as client:
        client.headers['Authorization']='Bearer '+owner
        assert client.get(ADMIN).json()['state']=='not_prepared'
        assert client.post(ADMIN,json={'revision':1,'policy_digest':'a'*64,'approve':True}).status_code==409
