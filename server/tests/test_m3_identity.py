from concurrent.futures import ThreadPoolExecutor
import copy
import uuid
import pytest
from fastapi.testclient import TestClient
from nova_directory.identity import verify_assertion
from nova_server.client_api import make_client_app
from nova_server.devices import DeviceError
from test_directory_control import control,initialize,publish,credentials


def arrange(control):
    initialize(control);entry=publish(control)['entry_id']
    with control.control.db() as db:owner=db.execute('SELECT account FROM publication').fetchone()[0]
    proof=control.remote.assertion(owner,entry)
    return entry,owner,proof


def test_directory_identity_entitlement_and_signature(control):
    entry,owner,proof=arrange(control)
    p=verify_assertion(proof,control.remote.identity_public,control.options['origin'],entry,
                       proof['payload']['audience'],proof['payload']['issued_at'])
    assert p['subject']==owner
    stranger=control.remote.login('another',credentials()['password'],'fixture')['account_id']
    with pytest.raises(Exception):control.remote.assertion(stranger,entry)
    control.remote.membership(owner,entry,'another',True)
    assert control.remote.assertion(stranger,entry)['payload']['subject']==stranger
    control.remote.membership(owner,entry,'another',False)
    with pytest.raises(Exception):control.remote.assertion(stranger,entry)


@pytest.mark.parametrize('field,value',[('subject',str(uuid.uuid4())),('audience',str(uuid.uuid4())),
    ('entry_id',str(uuid.uuid4())),('issuer','https://127.0.0.1:9999'),('username','forged'),('expires_at',9999999999)])
def test_tampered_or_wrong_audience_proof_rejected(control,field,value):
    _,_,proof=arrange(control);bad=copy.deepcopy(proof);bad['payload'][field]=value
    app=make_client_app(control.store.dir,control.options['client_origin'])
    with TestClient(app,base_url=control.options['client_origin']) as tv:
        assert tv.post('/api/v1/device/authorize',json={'label':'TV','assertion':bad}).status_code==403
    with control.store._db() as db:assert db.execute('SELECT COUNT(*) FROM device_requests').fetchone()[0]==0


def test_bound_grant_replay_permissions_and_member_revocation(control):
    _,owner,proof=arrange(control);app=make_client_app(control.store.dir,control.options['client_origin'])
    devices=app.state.devices
    with TestClient(app,base_url=control.options['client_origin']) as tv:
        assert tv.post('/api/v1/device/authorize',json={'label':'TV'}).status_code==403
        grant=tv.post('/api/v1/device/authorize',json={'label':'TV','assertion':proof}).json()
        assert tv.post('/api/v1/device/authorize',json={'label':'TV','assertion':proof}).status_code==409
        review=devices.inspect(grant['user_code']);assert review['account_id']==owner and review['account_name']=='owner'
        with pytest.raises(DeviceError) as error:devices.decide(grant['user_code'],review['request_id'],True)
        assert error.value.code=='member_permissions_required'
        with control.store._db() as db:
            db.execute("INSERT INTO member_accounts(subject,username,disabled) VALUES(?,'owner',0)",(owner,))
        devices.decide(grant['user_code'],review['request_id'],True)
        tokens=tv.post('/api/v1/device/token',json={'device_code':grant['device_code']}).json()
        assert devices.authenticate(tokens['access_token'])['account_id']==owner
        with control.store._db() as db:db.execute('UPDATE member_accounts SET disabled=1 WHERE subject=?',(owner,))
        with pytest.raises(DeviceError):devices.authenticate(tokens['access_token'])
        assert tv.post('/api/v1/device/refresh',json={'refresh_token':tokens['refresh_token']}).status_code==401


def test_assertion_single_use_under_concurrent_requests(control):
    _,_,proof=arrange(control);app=make_client_app(control.store.dir,control.options['client_origin'])
    def submit(_):
        with TestClient(app,base_url=control.options['client_origin']) as tv:
            return tv.post('/api/v1/device/authorize',json={'label':'TV','assertion':proof}).status_code
    with ThreadPoolExecutor(2) as executor:assert sorted(executor.map(submit,range(2)))==[201,409]


def test_expired_and_retargeted_assertions(control):
    entry,_,proof=arrange(control);p=proof['payload']
    for origin,server,now in ((control.options['origin'],p['audience'],p['expires_at']),
                              (control.options['origin'],str(uuid.uuid4()),p['issued_at']),
                              ('https://127.0.0.1:9999',p['audience'],p['issued_at'])):
        with pytest.raises(Exception):verify_assertion(proof,control.remote.identity_public,origin,entry,server,now)
