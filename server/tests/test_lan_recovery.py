import io
import json
import sqlite3
import tarfile
import time
import shutil
from contextlib import closing
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.lan_install import prepare
from scripts.lan_recovery import validate_lan,deployment_values,revoke_lan,write_restored_guidance
from scripts.recovery import files_for_backup,extract_checked,revoke_restored_sessions
from nova_directory.store import Registry,DirectoryError
from nova_directory.protocol import Descriptor,ChallengeRequest,Proof,encode,message
from nova_directory.client import server_identity
from nova_server.directory_control import DirectoryControl
from nova_server.directory_proof import verify_device_assertion
from nova_server.devices import DeviceError
from nova_server.storage import Store
from nova_server.secret_vault import SecretVault

IMAGE='ghcr.io/sphinkz10/nova-core@sha256:'+'a'*64
PASSWORD='recovery-fixture-password'


def publish(state,registry,info):
    config=validate_lan(state)['config'];sid,key=server_identity(state/'nova')
    descriptor=Descriptor(server_id=sid,name='Casa',client_origin=info['client'],
        certificate_pem=(state/'identity/client/server.crt').read_text())
    challenge=registry.challenge(config['operator_id'],ChallengeRequest(public_key=encode(key.public_key().public_bytes_raw()),descriptor=descriptor))
    record=registry.register(config['operator_id'],Proof(challenge_id=challenge['challenge_id'],signature=encode(key.sign(message(challenge)))))
    with closing(sqlite3.connect(state/'nova/directory-control.sqlite3')) as db,db:
        db.execute('UPDATE publication SET account=?,record=?,issuer_public=?,renewal_credential=?,renewal_expires_at=? WHERE id=1',
            (config['operator_id'],json.dumps(record),registry.identity_public,b'old-sealed-agent',int(time.time())+1000))
    return record


@pytest.fixture
def lan_state(tmp_path):
    bundle=tmp_path/'bundle';info=prepare(bundle,ip='192.168.50.20',state_root='/mnt/pool/nova',
        media_a='/mnt/pool/a',media_b='/mnt/pool/b',uid=10001,gid=10001,image=IMAGE,
        version='25.10.5',username='owner',password=PASSWORD)
    state=bundle/'copiar-para-nas';jf=state/'jellyfin/config/data';jf.mkdir()
    with closing(sqlite3.connect(jf/'jellyfin.db')) as db,db:
        db.executescript('CREATE TABLE Users(Id TEXT); INSERT INTO Users VALUES("owner");'
            'CREATE TABLE Devices(Id TEXT); INSERT INTO Devices VALUES("old-device");'
            'CREATE TABLE ApiKeys(Id TEXT); INSERT INTO ApiKeys VALUES("old-api-key");')
    DirectoryControl(state/'nova',origin=info['tv_directory'],ca=state/'identity/admin/lan-ca.crt',
        client_origin=info['client'],certificate=state/'identity/admin/client.crt')
    registry=Registry(state/'directory',info['tv_directory'])
    return bundle,state,info,registry


def test_complete_state_includes_keys_but_excludes_offline_ca_media_and_cache(lan_state):
    bundle,state,info,registry=lan_state
    observed=validate_lan(state);assert observed['fingerprint']==info['tv_fingerprint'] and not observed['tls_rotation_required']
    text=(bundle/'instalar-no-truenas.yaml').read_text()
    assert deployment_values(state,text)['state_root']=='/mnt/pool/nova'
    (state/'jellyfin/cache/omit').write_bytes(b'cache')
    _,files=files_for_backup(state)
    names={p.relative_to(state).as_posix() for p in files}
    assert 'directory/directory.sqlite3' in names and 'directory/directory-identity.key' in names
    assert all('identity/'+role+'/server.key' in names for role in ('admin','client','directory'))
    assert 'nova/directory-signing.key' in names and not any('cache/' in n or 'ca.key' in n for n in names)
    assert bundle/'GUARDAR-OFFLINE-ca.key' not in files


@pytest.mark.parametrize('missing',['directory/directory-identity.key','directory/directory.sqlite3','identity/client/server.key'])
def test_missing_identity_is_never_regenerated(lan_state,missing):
    _,state,_,_=lan_state;path=state/missing;path.unlink()
    with pytest.raises((ValueError,FileNotFoundError)):validate_lan(state)
    assert not path.exists()


@pytest.mark.parametrize('change',['tls_key','issuer_key','deployment','unknown_identity_file','sqlite_trigger'])
def test_inconsistent_or_executable_state_refused(lan_state,change):
    _,state,_,_=lan_state
    if change=='tls_key':(state/'identity/client/server.key').write_bytes((state/'identity/admin/server.key').read_bytes())
    elif change=='issuer_key':
        (state/'directory/directory-identity.key').write_bytes(Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    elif change=='deployment':
        path=state/'identity/client/deployment.json';data=json.loads(path.read_text());data['ports']['client']+=1;path.write_text(json.dumps(data))
    elif change=='unknown_identity_file':(state/'identity/admin/ca.key').write_bytes(b'forbidden')
    else:
        with closing(sqlite3.connect(state/'directory/directory.sqlite3')) as db,db:
            db.execute('CREATE TRIGGER retain_sessions AFTER DELETE ON sessions BEGIN SELECT 1; END')
    with pytest.raises((ValueError,FileNotFoundError)):validate_lan(state)


def test_recovery_never_replays_deployment_commands_and_only_rebinds_state(lan_state,tmp_path):
    bundle,state,info,_=lan_state;text=(bundle/'instalar-no-truenas.yaml').read_text()
    altered=json.loads(text);altered['services']['nova-admin']['privileged']=True
    with pytest.raises(ValueError):deployment_values(state,json.dumps(altered))
    staging=tmp_path/'restored';staging.mkdir();shutil.copytree(state,staging/'state')
    write_restored_guidance(staging,{'deployment':text},state_root='/mnt/pool/recovered',image=IMAGE)
    config=json.loads((staging/'instalar-no-truenas.yaml').read_text())
    assert config['services']['nova-client']['volumes'][0]['source']=='/mnt/pool/recovered/nova'
    assert config['services']['nova-directory']['volumes'][0]['source']=='/mnt/pool/recovered/directory'
    assert 'ports' not in config['services']['jellyfin']
    assert json.loads((staging/'RECUPERACAO.json').read_text())['fingerprint']==info['tv_fingerprint']
    with pytest.raises(ValueError):write_restored_guidance(staging,{'deployment':text},state_root='/mnt/pool/a',image=IMAGE)


def test_recovery_revokes_capabilities_and_old_assertions_without_replacing_trust(lan_state):
    _,state,info,registry=lan_state;record=publish(state,registry,info)
    operator=record['payload']['owner_id'];entry=record['payload']['entry_id']
    family=registry.create_account('alice',PASSWORD,share_entry=entry,owner=operator)
    old_session=registry.login('alice',PASSWORD,'fixture')['access_token']
    old_agent=registry.renewal_credential(operator,entry)['credential']
    moment=int(time.time());registry.clock=lambda:moment
    assertion=registry.assertion(family,entry)
    store=Store(state/'nova');store.save_session('old-admin')
    with store._db() as db:
        db.execute('INSERT INTO member_accounts(subject,username,credential,disabled) VALUES(?,?,?,0)',(family,'alice',b'old-sealed-media'))
    keys=[state/'directory/directory-identity.key',state/'nova/directory-signing.key',*list((state/'identity').rglob('*.*'))]
    before={p:p.read_bytes() for p in keys if p.is_file()}
    revoke_restored_sessions(state);revoke_lan(state,now=moment)
    assert all(p.read_bytes()==raw for p,raw in before.items())
    assert validate_lan(state)['server_id']==record['payload']['descriptor']['server_id']
    assert not store.session_valid('old-admin') and registry.discover(family)==[]
    with pytest.raises(DirectoryError):registry.authenticate(old_session)
    with pytest.raises(DirectoryError):registry._agent(old_agent)
    with store._db() as db:assert db.execute('SELECT disabled,credential FROM member_accounts').fetchone()==(1,None)
    with registry.db() as db:
        assert db.execute('SELECT COUNT(*) FROM members').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]==2
    registry.clock=lambda:moment+2;publish(state,registry,info)
    server=record['payload']['descriptor']['server_id']
    with pytest.raises(DeviceError):verify_device_assertion(state/'nova',server,assertion,now=moment+2)
    fresh=registry.assertion(family,entry)
    assert verify_device_assertion(state/'nova',server,fresh,now=moment+2)['subject']==family
    revoke_lan(state,now=moment-50)
    with store._db() as db:assert db.execute('SELECT not_before FROM identity_recovery_barrier').fetchone()[0]==moment


def test_format_one_cannot_smuggle_lan_state(tmp_path):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as archive:
        for name,data in [('manifest.json',json.dumps({'format':1,'nova_schema':3,'deployment':'{}'}).encode()),
                          ('state/identity/client/server.key',b'not-legacy')]:
            item=tarfile.TarInfo(name);item.size=len(data);archive.addfile(item,io.BytesIO(data))
    stream.seek(0)
    with pytest.raises(ValueError,match='legado'):extract_checked(stream,tmp_path)


@pytest.mark.parametrize('missing',[True,False])
def test_sealing_key_is_required_when_its_identity_is_pinned(lan_state,missing):
    _,state,_,_=lan_state;SecretVault(Store(state/'nova')).seal('fixture','fixture')
    key=state/'nova/member-secrets.key'
    if missing:key.unlink()
    else:key.write_bytes(b'x'*32)
    with pytest.raises(ValueError,match='credenciais'):validate_lan(state)
    assert not key.exists() if missing else key.read_bytes()==b'x'*32


def test_offline_recovery_preserves_expired_tls_and_reports_rotation(lan_state,monkeypatch):
    from datetime import datetime,timezone
    import scripts.lan_recovery as recovery
    class Future(datetime):
        @classmethod
        def now(cls,tz=None):return datetime(2030,1,1,tzinfo=timezone.utc)
    monkeypatch.setattr(recovery,'datetime',Future)
    assert recovery.validate_lan(lan_state[1])['tls_rotation_required']
