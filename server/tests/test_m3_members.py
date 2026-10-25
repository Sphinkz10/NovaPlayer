import asyncio
import copy
import json
import re
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from nova_server.client_api import make_client_app
from nova_server.devices import Devices,DeviceError
from nova_server.members import Members,MemberConfiguration
from nova_server.setup import SetupError
from nova_server.storage import Store


from jellyfin_m3_fixture import JellyfinMembers

@pytest.fixture
def members(tmp_path):
    store=Store(tmp_path);store.bootstrap('owner','unused');jf=JellyfinMembers()
    libs=[{'id':uuid.uuid4().hex,'name':name} for name in ('Biblioteca A','Biblioteca B')]
    with store._db() as db:
        db.execute('UPDATE jellyfin_setup SET server_id=?,report=? WHERE id=1',(jf.sid,json.dumps({'server_id':jf.sid,'libraries':libs})))
    service=Members(store,'http://jellyfin:8096',httpx.MockTransport(jf))
    service.fixture_jf=jf;service.fixture_libs=libs;service.fixture_subjects=[]
    for name in ('alice','bruno'):
        subject=str(uuid.uuid4());service.fixture_subjects.append(subject)
        Devices(store).start('TV '+name,{'audience':Devices(store).identity(),'expires_at':int(time.time())+90,
            'assertion_id':str(uuid.uuid4()),'subject':subject,'username':name,'entry_id':str(uuid.uuid4())})
    return service


def configure(service,index=0,libraries=None,**extra):
    payload=MemberConfiguration(username='owner',password='owner-fixture-password',subject=service.fixture_subjects[index],
        libraries=libraries or [service.fixture_libs[index]['id']],**extra)
    return asyncio.run(service.configure(payload))


def issue(service,index=0):
    devices=Devices(service.store);subject=service.fixture_subjects[index]
    with service.store._db() as db:
        row=db.execute('SELECT id FROM device_requests WHERE account_id=?',(subject,)).fetchone()
        # A direct fixture grant still exercises token issuance and dynamic member checks.
        db.execute('INSERT INTO devices(id,label,created_at,expires_at,account_id,account_name) VALUES(?,?,?,?,?,?)',
            (row[0],'TV',int(time.time()),int(time.time())+86400,subject,'fixture'))
        return devices._issue(db,row[0],int(time.time()),int(time.time())+86400)


def test_restricted_jellyfin_policy_and_encrypted_credentials(members):
    result=configure(members);subject=members.fixture_subjects[0]
    assert result['administrator'] is False and result['jellyfin_policy_verified']
    with members.store._db() as db:uid,raw=db.execute('SELECT jellyfin_user,credential FROM member_accounts WHERE subject=?',(subject,)).fetchone()
    user=members.fixture_jf.users[uid];policy=user['Policy']
    assert policy['EnableAllFolders'] is False and policy['EnabledFolders']==[members.fixture_libs[0]['id']]
    assert not policy['IsAdministrator'] and not policy['EnableMediaDeletion'] and not policy['EnableContentDownloading']
    credential=members.vault.open(raw,'member:'+subject+':'+members.fixture_jf.sid)
    assert credential.encode() not in raw and 'owner-fixture-password' not in str(result)
    assert set(members.fixture_jf.tokens.values())=={uid} # administrative session logged out


def test_two_accounts_library_isolation_and_scope(members,monkeypatch):
    configure(members,0);configure(members,1)
    first,second=issue(members,0),issue(members,1)
    monkeypatch.setattr('nova_server.members.Members',lambda *args,**kwargs:members)
    app=make_client_app(members.store.dir,'https://127.0.0.1:8920')
    with TestClient(app,base_url='https://127.0.0.1:8920') as client:
        for index,tokens in enumerate((first,second)):
            headers={'Authorization':'Bearer '+tokens['access_token']}
            result=client.get('/api/v1/device/libraries',headers=headers)
            assert result.status_code==200 and result.json()['libraries']==[members.fixture_libs[index]]
            own=members.fixture_libs[index]['id'];other=members.fixture_libs[1-index]['id']
            assert client.get('/api/v1/device/libraries/'+own+'/authorization',headers=headers).status_code==200
            assert client.get('/api/v1/device/libraries/'+other+'/authorization',headers=headers).status_code==404
            assert client.get('/api/v1/admin/members',headers=headers).status_code==404
        assert client.get('/api/v1/device/libraries').status_code==401


def test_unknown_account_or_library_rejected(members):
    with pytest.raises(SetupError):configure(members,libraries=[uuid.uuid4().hex])
    with pytest.raises(SetupError):asyncio.run(members.configure(MemberConfiguration(username='owner',password='fixture',
        subject=str(uuid.uuid4()),libraries=[members.fixture_libs[0]['id']])))


def test_remote_policy_change_fails_closed(members):
    configure(members);tokens=issue(members)
    with members.store._db() as db:uid=db.execute('SELECT jellyfin_user FROM member_accounts').fetchone()[0]
    members.fixture_jf.users[uid]['Policy']['EnableAllFolders']=True
    with pytest.raises(SetupError):asyncio.run(members.authorization(tokens['access_token']))


def test_member_revocation_and_credentials_never_reused(members):
    configure(members);tokens=issue(members)
    members.revoke(members.fixture_subjects[0])
    with pytest.raises(DeviceError):asyncio.run(members.authorization(tokens['access_token']))
    with pytest.raises(DeviceError):Devices(members.store).refresh(tokens['refresh_token'])
    with members.store._db() as db:assert db.execute('SELECT credential FROM member_accounts').fetchone()[0] is None


def test_policy_update_rotates_restricted_credential(members):
    configure(members)
    with members.store._db() as db:old=db.execute('SELECT credential FROM member_accounts').fetchone()[0]
    configure(members,libraries=[members.fixture_libs[1]['id']])
    with members.store._db() as db:new,revision=db.execute('SELECT credential,revision FROM member_accounts').fetchone()
    assert old!=new and revision==2
    assert len(members.fixture_jf.tokens)==1


def test_missing_key_cannot_replace_encryption_identity(members):
    configure(members);tokens=issue(members);path=members.store.dir/'member-secrets.key';path.unlink()
    with pytest.raises(DeviceError):asyncio.run(members.authorization(tokens['access_token']))
    assert not path.exists()
    with pytest.raises(SetupError):configure(members,1)
    assert not path.exists()


def test_concurrent_revocation_cannot_be_overwritten_by_provisioning(members):
    original=members.vault.seal
    def revoke_before_commit(*args):
        sealed=original(*args);members.revoke(members.fixture_subjects[0]);return sealed
    members.vault.seal=revoke_before_commit
    with pytest.raises(SetupError,match='member_permissions_changed'):configure(members)
    with members.store._db() as db:
        assert db.execute('SELECT disabled,credential FROM member_accounts').fetchone()==(1,None)
