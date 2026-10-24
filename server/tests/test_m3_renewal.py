import json
import uuid
import pytest
from nova_directory.protocol import Descriptor,Proof,encode,message
from nova_directory.store import DirectoryError
from test_directory_control import control,initialize,publish,credentials


def published(control):
    initialize(control);result=publish(control)
    with control.control.db() as db:
        account,record,sealed=db.execute('SELECT account,record,renewal_credential FROM publication').fetchone()
    server=json.loads(record)['payload']['descriptor']['server_id']
    token=control.control.vault.open(sealed,'directory-renewal:'+control.options['origin']+':'+server)
    return result,account,token


def test_scoped_renewal_without_saved_password(control):
    original,_,token=published(control)
    with control.remote.db() as db:
        assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
        retained=str(db.execute('SELECT * FROM registration_agents').fetchall())
        assert token not in retained and credentials()['password'] not in retained
    result=control.control.renew_if_due(force=True)
    assert result['entry_id']==original['entry_id'] and result['version']==2
    assert result['state']=='renewed_at_check'
    with control.control.db() as db:
        assert credentials()['password'] not in str(db.execute('SELECT * FROM publication').fetchall())


def test_agent_cannot_login_discover_share_or_renew_other_server(control):
    _,_,token=published(control)
    with pytest.raises(DirectoryError):control.remote.authenticate(token)
    with control.control.db() as db:record=json.loads(db.execute('SELECT record FROM publication').fetchone()[0])
    descriptor=Descriptor.model_validate(record['payload']['descriptor'])
    descriptor.server_id=str(uuid.uuid4())
    with pytest.raises(DirectoryError) as error:control.remote.agent_challenge(token,descriptor)
    assert error.value.status==403


def test_rotated_and_disabled_renewal_credentials_refused(control):
    first,owner,token=published(control)
    control.remote.renewal_credential(owner,first['entry_id'])
    with pytest.raises(DirectoryError):control.remote._agent(token)
    next_token=control.remote.renewal_credential(owner,first['entry_id'])['credential']
    control.remote.disable_account('owner')
    with pytest.raises(DirectoryError):control.remote._agent(next_token)


def test_server_removal_and_expiration_stop_agent(control,monkeypatch):
    first,owner,token=published(control)
    control.remote.remove(owner,first['entry_id'])
    with pytest.raises(DirectoryError):control.remote._agent(token)


def test_agent_proof_replay_and_scope_binding(control):
    _,owner,token=published(control)
    _,key,_,_=control.control.identity()
    with control.control.db() as db:record=json.loads(db.execute('SELECT record FROM publication').fetchone()[0])
    descriptor=Descriptor.model_validate(record['payload']['descriptor'])
    payload=control.remote.agent_challenge(token,descriptor)
    proof=Proof(challenge_id=payload['challenge_id'],signature=encode(key.sign(message(payload))))
    with pytest.raises(DirectoryError):control.remote.register(owner,proof)
    renewed=control.remote.agent_register(token,proof);assert renewed['payload']['version']==2
    with pytest.raises(DirectoryError):control.remote.agent_register(token,proof)


def test_renewal_requires_prior_credential(control):
    initialize(control)
    assert control.post('/api/v1/admin/directory/renew').status_code==409


def test_due_window_renews_without_owner_session(control,monkeypatch):
    import time
    from types import SimpleNamespace
    published(control)
    assert control.control.renew_if_due()['version']==1
    now=time.time()
    monkeypatch.setattr('nova_server.directory_control.time',SimpleNamespace(time=lambda:now+2800))
    assert control.control.renew_if_due()['version']==2


def test_application_lifespan_runs_and_stops_renewal_worker(control,monkeypatch):
    import asyncio
    import threading
    called=threading.Event();original_sleep=asyncio.sleep
    async def short_interval(delay,*args):
        return await original_sleep(0.01 if delay==60 else delay,*args)
    monkeypatch.setattr('nova_server.app.asyncio.sleep',short_interval)
    monkeypatch.setattr(control.control,'renew_if_due',lambda:called.set())
    with control:
        assert control.control.worker_active
        assert called.wait(3)
    assert not control.control.worker_active
