from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from nova_server.app import make_app
from nova_server.client_api import make_client_app, client_origin
from nova_server.devices import Devices, DeviceError, ACCESS_TTL, DEVICE_TTL
from nova_server.storage import Store
from scripts.recovery import revoke_restored_sessions


@pytest.fixture
def pair(tmp_path):
    state = tmp_path/'nova'
    store = Store(state)
    store.bootstrap('owner', 'unused-hash')
    owner_token = 'owner-'+'a'*48
    store.save_session(owner_token)
    admin_app = make_app(state, allowed_hosts=['testserver'])
    client_app = make_client_app(state, origin='https://nova.test:8920')
    clock = [2000000000]
    admin_app.state.devices.clock = client_app.state.devices.clock = lambda: clock[0]
    with TestClient(admin_app) as admin, TestClient(client_app, base_url='https://nova.test:8920') as client:
        admin.headers['Authorization'] = 'Bearer '+owner_token
        yield admin, client, client_app.state.devices, clock


def approved(pair, label='Living room TV'):
    admin, client, service, _ = pair
    grant = client.post('/api/v1/device/authorize', json={'label': label}).json()
    review = admin.post('/api/v1/admin/devices/inspect', json={'user_code': grant['user_code']})
    assert review.status_code == 200, review.text
    result = admin.post('/api/v1/admin/devices/decision', json={
        'user_code': grant['user_code'], 'request_id': review.json()['request_id'], 'approve': True})
    assert result.status_code == 200
    return grant


def tokens(pair):
    grant = approved(pair)
    result = pair[1].post('/api/v1/device/token', json={'device_code': grant['device_code']})
    assert result.status_code == 200, result.text
    return grant, result.json()


def test_pair_refresh_revoke_and_role_separation(pair):
    admin, client, service, _ = pair
    grant, issued = tokens(pair)
    headers = {'Authorization': 'Bearer '+issued['access_token']}
    me = client.get('/api/v1/device/me', headers=headers)
    assert me.status_code == 200
    assert me.json()['server_id'] == grant['server_id']
    assert me.json()['scope'] == 'device:read'
    assert not me.json()['descriptor']['media_enabled']
    assert admin.get('/api/v1/admin/devices', headers=headers).status_code == 401
    assert client.get('/api/v1/device/me', headers=dict(admin.headers)).status_code == 401
    for path in ('/api/v1/admin/devices', '/api/v1/admin/overview', '/', '/static/control.js', '/Users', '/docs'):
        assert client.get(path, headers=dict(admin.headers)).status_code == 404
    assert admin.post('/api/v1/device/token', json={'device_code': grant['device_code']}).status_code == 404
    rotated = client.post('/api/v1/device/refresh', json={'refresh_token': issued['refresh_token']}).json()
    assert rotated['refresh_token'] != issued['refresh_token']
    assert client.get('/api/v1/device/me', headers=headers).status_code == 401
    new_headers = {'Authorization': 'Bearer '+rotated['access_token']}
    assert client.get('/api/v1/device/me', headers=new_headers).status_code == 200
    assert admin.delete('/api/v1/admin/devices/'+issued['device_id']).json() == {'revoked': True}
    assert client.get('/api/v1/device/me', headers=new_headers).status_code == 401
    assert client.post('/api/v1/device/refresh', json={'refresh_token': rotated['refresh_token']}).status_code == 401


def test_pending_polling_backoff_commits_and_expiry(pair):
    admin, client, service, clock = pair
    grant = client.post('/api/v1/device/authorize', json={'label':'TV'}).json()
    payload = {'device_code': grant['device_code']}
    assert client.post('/api/v1/device/token', json=payload).json()['error'] == 'authorization_pending'
    result = client.post('/api/v1/device/token', json=payload)
    assert result.status_code == 429 and result.headers['Retry-After'] == '10'
    clock[0] += 6
    assert client.post('/api/v1/device/token', json=payload).headers['Retry-After'] == '15'
    clock[0] += 601
    assert admin.post('/api/v1/admin/devices/inspect', json={'user_code':grant['user_code']}).status_code == 404
    assert client.post('/api/v1/device/token', json=payload).status_code == 400


def test_denial_and_decision_cannot_be_replayed(pair):
    admin, client, service, _ = pair
    grant = service.start('TV')
    review = service.inspect(grant['user_code'])
    payload = {'user_code':grant['user_code'], 'request_id':review['request_id'], 'approve':False}
    assert admin.post('/api/v1/admin/devices/decision', json=payload).status_code == 200
    payload['approve'] = True
    assert admin.post('/api/v1/admin/devices/decision', json=payload).status_code == 409
    assert client.post('/api/v1/device/token', json={'device_code':grant['device_code']}).json()['error'] == 'access_denied'


def test_approval_requires_matching_review_and_owner(pair):
    admin, client, service, _ = pair
    first, second = service.start('TV one'), service.start('TV two')
    review = service.inspect(first['user_code'])
    data = {'user_code':second['user_code'], 'request_id':review['request_id'], 'approve':True}
    assert admin.post('/api/v1/admin/devices/decision', json=data).status_code == 409
    assert admin.post('/api/v1/admin/devices/inspect', json={'user_code': first['user_code']},
                      headers={'Authorization':'Bearer invalid'}).status_code == 401
    assert admin.delete('/api/v1/admin/devices/anything', headers={'Authorization':''}).status_code == 401


def test_concurrent_grant_consumption_is_single_use_across_workers(pair):
    grant = approved(pair)
    service = pair[2]
    other = Devices(Store(service.store.dir), service.clock)
    def attempt(worker):
        try:
            return worker.poll(grant['device_code'])
        except DeviceError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (service, other)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 'invalid_grant' in results


def test_refresh_replay_revokes_successor_and_other_device_survives(pair):
    _, first = tokens(pair)
    _, second = tokens(pair)
    service = pair[2]
    rotated = service.refresh(first['refresh_token'])
    with pytest.raises(DeviceError):
        service.refresh(first['refresh_token'])
    for access in (first['access_token'], rotated['access_token']):
        with pytest.raises(DeviceError):
            service.authenticate(access)
    with pytest.raises(DeviceError):
        service.refresh(rotated['refresh_token'])
    assert service.authenticate(second['access_token'])['device_id'] == second['device_id']


def test_concurrent_refresh_detects_reuse_across_workers(pair):
    _, issued = tokens(pair)
    service = pair[2]
    other = Devices(Store(service.store.dir), service.clock)
    def attempt(worker):
        try:
            return worker.refresh(issued['refresh_token'])
        except DeviceError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (service, other)))
    assert sum(result is not None for result in results) == 1
    with pytest.raises(DeviceError):
        service.authenticate(next(result for result in results if result)['access_token'])


def test_credentials_hashed_no_response_leaks_and_identity_persists(pair):
    grant, issued = tokens(pair)
    admin, client, service, clock = pair
    with sqlite3.connect(service.store.path) as db:
        dump = '\n'.join(db.iterdump())
    for secret in (grant['device_code'], grant['user_code'].replace('-',''), issued['access_token'], issued['refresh_token']):
        assert secret not in dump
        assert secret not in admin.get('/api/v1/admin/devices').text
    again = Devices(Store(service.store.dir), service.clock)
    assert again.identity() == service.identity()
    assert again.authenticate(issued['access_token'])['device_id'] == issued['device_id']
    invalid = client.post('/api/v1/device/refresh', json={'refresh_token': issued['refresh_token'], 'extra':'secret'})
    assert invalid.status_code == 422 and issued['refresh_token'] not in invalid.text
    assert invalid.headers['Cache-Control'] == 'no-store'


def test_tokens_expire_and_refresh_never_extends_absolute_lifetime(pair):
    _, issued = tokens(pair)
    service, clock = pair[2:]
    clock[0] += ACCESS_TTL
    with pytest.raises(DeviceError):
        service.authenticate(issued['access_token'])
    fresh = service.refresh(issued['refresh_token'])
    assert fresh['refresh_expires_in'] == DEVICE_TTL-ACCESS_TTL
    clock[0] += DEVICE_TTL
    with pytest.raises(DeviceError):
        service.refresh(fresh['refresh_token'])


def test_server_isolation(pair, tmp_path):
    grant, issued = tokens(pair)
    other = Devices(Store(tmp_path/'other'), pair[2].clock)
    assert other.identity() != grant['server_id']
    for fn, secret in ((other.poll, grant['device_code']), (other.refresh, issued['refresh_token']),
                       (other.authenticate, issued['access_token'])):
        with pytest.raises(DeviceError):
            fn(secret)


def test_https_required_even_with_spoofed_forwarded_header(pair):
    client = pair[1]
    result = client.post('http://nova.test:8920/api/v1/device/authorize', json={'label':'TV'},
                         headers={'X-Forwarded-Proto':'https'})
    assert result.status_code == 400 and result.json()['error'] == 'https_required'
    assert client.post('https://wrong.test/api/v1/device/authorize', json={'label':'TV'}).status_code == 400
    assert client.post('/api/v1/device/authorize', content=b'x'*4097).status_code == 413
    assert client.post('/api/v1/device/authorize', content=iter([b'x'*2048,b'x'*2050])).status_code == 413


def test_rate_limits_include_all_workers_and_no_proxy_ip_trust(pair):
    admin, client, service, clock = pair
    for n in range(10):
        assert client.post('/api/v1/device/authorize', json={'label':'TV'},
                           headers={'X-Forwarded-For': f'10.1.1.{n}'}).status_code == 201
    assert client.post('/api/v1/device/authorize', json={'label':'TV'}).status_code == 429
    other = Devices(Store(service.store.dir), service.clock)
    with pytest.raises(DeviceError):
        other.limit('authorize', 'testclient', 10, 64)
    clock[0] += 601
    assert client.post('/api/v1/device/authorize', json={'label':'TV'}).status_code == 201


def test_global_rate_limit_bounds_source_cardinality(pair):
    service = pair[2]
    for n in range(64):
        service.limit('authorize', str(n), 10, 64)
    with pytest.raises(DeviceError):
        service.limit('authorize', 'new-source', 10, 64)
    with sqlite3.connect(service.store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM device_limits').fetchone()[0] == 65


def test_owner_code_guess_budget_and_request_scope_cannot_be_escalated(pair):
    admin, client, _, _ = pair
    for _ in range(20):
        assert admin.post('/api/v1/admin/devices/inspect', json={'user_code':'INVALIDX'}).status_code == 404
    assert admin.post('/api/v1/admin/devices/inspect', json={'user_code':'INVALIDX'}).status_code == 429
    for payload in ({'label':'TV','scope':'admin'}, {'label':''}, {'label':'TV\nname'},
                    {'label':'TV','expires_in':999999}):
        assert client.post('/api/v1/device/authorize', json=payload).status_code == 422


def test_no_device_grants_before_owner_setup(tmp_path):
    with TestClient(make_client_app(tmp_path, origin='https://nova.test'), base_url='https://nova.test') as client:
        assert client.post('/api/v1/device/authorize', json={'label':'TV'}).status_code == 409


def test_device_logout_revokes_only_itself_and_rejects_admin_token(pair):
    _, first = tokens(pair)
    _, second = tokens(pair)
    admin, client, service, _ = pair
    assert client.post('/api/v1/device/logout', headers=dict(admin.headers)).status_code == 401
    result = client.post('/api/v1/device/logout', headers={'Authorization':'Bearer '+first['access_token']})
    assert result.status_code == 200 and result.json()['revoked'] is True
    with pytest.raises(DeviceError):
        service.refresh(first['refresh_token'])
    assert service.authenticate(second['access_token'])['device_id'] == second['device_id']


def test_restore_revokes_pending_grants_and_all_device_credentials(pair, tmp_path):
    grant, issued = tokens(pair)
    service = pair[2]
    pending = approved(pair)
    config = tmp_path/'jellyfin/config/data'; config.mkdir(parents=True)
    with sqlite3.connect(config/'jellyfin.db') as db:
        db.executescript("CREATE TABLE Users(Id TEXT); INSERT INTO Users VALUES('owner');"
                         'CREATE TABLE Devices(Id TEXT); CREATE TABLE ApiKeys(Id TEXT);')
    revoke_restored_sessions(tmp_path)
    assert service.identity() == grant['server_id']
    assert service.list()[0]['revoked'] == 1
    for fn, secret in ((service.poll,pending['device_code']), (service.refresh,issued['refresh_token']),
                       (service.authenticate,issued['access_token'])):
        with pytest.raises(DeviceError):
            fn(secret)


@pytest.mark.parametrize('origin', ['', 'http://nova.test', 'https://u:p@nova.test', 'https://nova.test/path',
                                  'https://nova.test?token=x', 'https://nova.test#fragment',
                                  'https://nova.test:99999', 'https://nova.test:', 'https://nova.test\\other'])
def test_invalid_https_origins(origin):
    with pytest.raises(ValueError):
        client_origin(origin)


def test_migrate_v1_retains_owner(tmp_path):
    path = tmp_path/'nova.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE admin(id INTEGER PRIMARY KEY,username TEXT,password_hash TEXT,created_at INTEGER);"
                        "INSERT INTO admin VALUES(1,'owner','hash',1); PRAGMA user_version=1;")
    store = Store(tmp_path)
    assert store.get_admin('owner') == (1,'hash')
    assert Devices(store).identity()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
