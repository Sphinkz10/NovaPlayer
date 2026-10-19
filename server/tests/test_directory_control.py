import pytest
from fastapi.testclient import TestClient

from nova_directory.api import make_directory
from nova_directory.client import DirectoryClient
from nova_server.app import make_app
from nova_server.directory_control import DirectoryControl, ControlError
from nova_server.storage import Store
from test_directory import certificate


@pytest.fixture
def control(tmp_path, monkeypatch):
    origin = 'https://127.0.0.1:9443'
    ca = tmp_path/'cert.pem'; ca.write_text(certificate()[0])
    remote = make_directory(tmp_path/'remote', origin)
    registry = remote.state.registry
    for username in ('owner','another'):
        registry.create_account(username,'disposable-directory-password')
    class InProcessClient(DirectoryClient):
        def __init__(self, origin, certificate):
            self.origin, self.token, self.account = origin, None, None
            self.http = TestClient(remote, base_url=origin)
    monkeypatch.setattr('nova_server.directory_control.DirectoryClient', InProcessClient)
    state = tmp_path/'nova'; store = Store(state); store.bootstrap('novaowner','unused')
    token = 'synthetic-owner-session-'+'x'*40; store.save_session(token)
    options = dict(origin=origin, ca=ca, client_origin='https://127.0.0.1:8920', certificate=ca)
    app = make_app(state, directory_options=options)
    client = TestClient(app, base_url='http://127.0.0.1'); client.headers['Authorization'] = 'Bearer '+token
    client.options, client.store, client.control, client.remote = options, store, app.state.directory_control, registry
    return client


def credentials(**extra):
    return dict(username='owner', password='disposable-directory-password', **extra)


def initialize(client):
    response = client.post('/api/v1/admin/directory/identity')
    assert response.status_code == 200 and response.json()['identity'] == 'ready'
    return response.json()


def publish(client):
    response = client.post('/api/v1/admin/directory/publish', json=credentials(name='Casa'))
    assert response.status_code == 200
    return response.json()


def test_control_register_renew_restart_and_verify(control):
    assert control.get('/api/v1/admin/directory').json()['identity'] == 'missing'
    identity = initialize(control)
    first = publish(control); second = publish(control)
    assert first['entry_id'] == second['entry_id'] and second['version'] == 2
    assert second['fingerprint'] == identity['fingerprint'] and not second['media_authorized']
    reopened = DirectoryControl(control.store.dir, **control.options)
    assert reopened.status()['entry_id'] == second['entry_id']
    checked = control.post('/api/v1/admin/directory/check',json=credentials()).json()
    assert checked['state'] == 'listed_at_check'
    with control.remote.db() as db:
        assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0
    with reopened.db() as db:
        retained = str(db.execute('SELECT * FROM publication').fetchall())
    assert credentials()['password'] not in retained and 'PRIVATE KEY' not in retained


@pytest.mark.parametrize('path', ['identity','publish','check'])
def test_owner_session_required(control, path):
    control.headers.clear()
    assert control.post('/api/v1/admin/directory/'+path,json=credentials(name='Casa')).status_code == 401
    assert control.get('/api/v1/admin/directory').status_code == 401
    assert not (control.store.dir/'directory-signing.key').exists()


def test_disabled_by_default_and_no_network_configuration_from_request(tmp_path):
    app = make_app(tmp_path); app.state.store.bootstrap('owner','unused')
    token='x'*48; app.state.store.save_session(token)
    with TestClient(app,base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+token}) as client:
        assert client.get('/api/v1/admin/directory').json()['enabled'] is False
        assert client.post('/api/v1/admin/directory/identity').status_code == 503


@pytest.mark.parametrize('field', ['origin','ca','certificate','state','client_origin','verify'])
def test_browser_cannot_override_destination_or_trust(control, field):
    payload=credentials(name='Casa'); payload[field]='password-sensitive-value'
    response=control.post('/api/v1/admin/directory/publish',json=payload)
    assert response.status_code == 422 and 'password-sensitive-value' not in response.text


def test_missing_key_never_silently_created(control):
    response=control.post('/api/v1/admin/directory/publish',json=credentials(name='Casa'))
    assert response.status_code == 502
    assert not (control.store.dir/'directory-signing.key').exists()


def test_account_continuity_before_remote_mutation(control):
    initialize(control); first=publish(control)
    response=control.post('/api/v1/admin/directory/publish',json={**credentials(name='Casa'),'username':'another'})
    assert response.status_code == 409 and response.json()['detail']=='directory_account_changed'
    assert control.get('/api/v1/admin/directory').json()['entry_id']==first['entry_id']
    with control.remote.db() as db:
        assert db.execute('SELECT COUNT(*) FROM entries').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0


def test_directory_origin_cannot_change_silently(control):
    with pytest.raises(ValueError,match='already bound'):
        DirectoryControl(control.store.dir,**{**control.options,'origin':'https://127.0.0.1:9444'})


def test_check_remote_removal_preserves_receipt_and_renewal_is_refused(control):
    initialize(control); first=publish(control)
    with control.control.db() as db:
        owner=db.execute('SELECT account FROM publication').fetchone()[0]
    control.remote.remove(owner,first['entry_id'])
    check=control.post('/api/v1/admin/directory/check',json=credentials()).json()
    assert check['state']=='not_listed_at_check' and check['entry_id']==first['entry_id']
    assert control.post('/api/v1/admin/directory/publish',json=credentials(name='Casa')).status_code==502


def test_busy_across_instances_and_password_not_reflected(control):
    initialize(control)
    with control.control.db(write=True):
        response=control.post('/api/v1/admin/directory/publish',json=credentials(name='Casa'))
    assert response.status_code==409 and response.json()['detail']=='directory_busy'
    assert credentials()['password'] not in response.text


def test_wrong_password_and_oversized_body(control):
    initialize(control)
    response=control.post('/api/v1/admin/directory/publish',json={**credentials(name='Casa'),'password':'secret-wrong'})
    assert response.status_code==502 and 'secret-wrong' not in response.text
    assert control.post('/api/v1/admin/directory/publish',content=b'x'*16385).status_code==413


def test_key_corruption_is_not_replaced(control):
    initialize(control); path=control.store.dir/'directory-signing.key'; path.write_bytes(b'broken')
    assert control.get('/api/v1/admin/directory').json()['identity']=='invalid'
    assert control.post('/api/v1/admin/directory/identity').status_code==502
    assert path.read_bytes()==b'broken'


def test_signing_rejects_regressed_challenge_before_submission(control, monkeypatch):
    initialize(control); publish(control)
    original=control.remote.challenge
    def regression(owner, request):
        payload=original(owner,request); payload['version']=1; return payload
    monkeypatch.setattr(control.remote,'challenge',regression)
    response=control.post('/api/v1/admin/directory/publish',json=credentials(name='Casa'))
    assert response.status_code==502
    with control.remote.db() as db:
        assert db.execute('SELECT version FROM entries').fetchone()[0]==1


def test_expired_receipt_is_not_reported_as_current(control, monkeypatch):
    initialize(control); result=publish(control)
    monkeypatch.setattr('nova_server.directory_control.time.time',lambda:result['expires_at']+1)
    assert control.control.status()['state']=='expired'


def test_lost_registration_response_preserves_account_binding(control, monkeypatch):
    initialize(control)
    original=DirectoryClient.register
    def lose_response(client, *args, **kwargs):
        original(client,*args,**kwargs)
        raise ValueError('response lost after remote registration')
    monkeypatch.setattr(DirectoryClient,'register',lose_response)
    response=control.post('/api/v1/admin/directory/publish',json=credentials(name='Casa'))
    assert response.status_code==502
    with control.control.db() as db:
        account,record=db.execute('SELECT account,record FROM publication').fetchone()
        assert account and record is None
    response=control.post('/api/v1/admin/directory/check',json={**credentials(),'username':'another'})
    assert response.status_code==409
    response=control.post('/api/v1/admin/directory/check',json=credentials())
    assert response.status_code==200 and response.json()['state']=='listed_at_check'


def test_expired_owner_session_is_denied(control):
    control.store.revoke_session(control.headers['Authorization'][7:])
    assert control.get('/api/v1/admin/directory').status_code==401
    assert control.post('/api/v1/admin/directory/identity').status_code==401


def test_missing_previously_published_key_requires_restore(control):
    initialize(control);publish(control)
    path=control.store.dir/'directory-signing.key';path.unlink()
    response=control.post('/api/v1/admin/directory/identity')
    assert response.status_code==409 and response.json()['detail']=='directory_identity_restore_required'
    assert not path.exists()


@pytest.mark.parametrize('response', [[], {'access_token':'x'*48,'account_id':'invalid'}])
def test_malformed_login_cannot_pin_a_directory_account(control, monkeypatch, response):
    initialize(control)
    monkeypatch.setattr(control.remote,'login',lambda *args:response)
    result=control.post('/api/v1/admin/directory/publish',json=credentials(name='Casa'))
    assert result.status_code==502
    with control.control.db() as db:
        assert db.execute('SELECT account FROM publication').fetchone()[0] is None
