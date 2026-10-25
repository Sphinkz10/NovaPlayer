import base64
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient

from nova_server.app import make_app
from nova_server.client_api import make_client_app
from nova_server.devices import DeviceError, Devices
from nova_server.members import Members
from nova_server.storage import Store
from nova_server.wireguard import WireGuardEnrollments
from scripts.recovery import revoke_restored_sessions
from test_recovery import state_fixture

ADMIN = '/api/v1/admin/connect/wireguard/enrollments'
CLIENT = '/api/v1/device/wireguard'


def key():
    return base64.b64encode(X25519PrivateKey.generate().public_key().public_bytes_raw()).decode()


def associate(service):
    request = service.start('TV <untrusted>')
    service.decide(request['user_code'], service.inspect(request['user_code'])['request_id'], True)
    return service.poll(request['device_code'])


@pytest.fixture
def lab(tmp_path):
    store = Store(tmp_path/'nova'); store.bootstrap('owner', 'unused')
    owner = 'owner-'+'a'*48; store.save_session(owner)
    with TestClient(make_app(store.dir, allowed_hosts=['testserver'])) as admin, TestClient(
            make_client_app(store.dir, origin='https://10.1.0.1:9444'), base_url='https://10.1.0.1:9444') as client:
        admin.headers['Authorization'] = 'Bearer '+owner
        service = Devices(store); tokens = associate(service)
        client.headers['Authorization'] = 'Bearer '+tokens['access_token']
        yield admin, client, service, tokens


def request(lab, public=None):
    result = lab[1].post(CLIENT, json={'public_key': public or key()})
    assert result.status_code == 200, result.text
    return result.json()


def approve(lab, item):
    return lab[0].post(ADMIN+'/'+item['device_id'], json={'revision': item['revision'], 'approve': True})


def test_request_approval_restart_and_truthful_state(lab):
    admin, client, service, _ = lab
    item = request(lab)
    assert item['state'] == 'pending' and item['gateway_state'] == 'not_verified'
    assert not item['remote_access_enabled']
    assert admin.get(ADMIN).json()['enrollments'] == [item]
    assert request(lab, item['public_key']) == item
    decided = approve(lab, item); assert decided.status_code == 200
    approved = decided.json(); assert approved['state'] == 'approved' and approved['revision'] == 2
    assert approved['gateway_state'] == 'not_verified' and not approved['remote_access_enabled']
    assert request(lab, item['public_key']) == approved
    assert WireGuardEnrollments(Store(service.store.dir)).list() == [approved]
    assert client.get(CLIENT).json() == approved
    assert admin.get('/api/v1/status').json()['remote_access_enabled'] is False


def test_device_and_admin_credentials_cannot_cross_roles_or_enumerate_other_tv(lab):
    admin, client, service, tokens = lab
    item = request(lab)
    assert approve(lab, item).status_code == 200
    assert admin.get(ADMIN, headers=dict(client.headers)).status_code == 401
    assert admin.post(ADMIN+'/'+item['device_id'], headers=dict(client.headers), json={'revision':2,'approve':False}).status_code == 401
    assert client.post(CLIENT, headers=dict(admin.headers), json={'public_key':key()}).status_code == 401
    assert client.get(ADMIN).status_code == 404
    assert client.post(ADMIN+'/'+item['device_id'], json={'revision':2,'approve':True}).status_code == 404
    other = associate(service)
    headers = {'Authorization':'Bearer '+other['access_token']}
    assert client.get(CLIENT, headers=headers).status_code == 404
    assert client.get(CLIENT+'/'+tokens['device_id'], headers=headers).status_code == 404
    assert client.post(CLIENT, headers=headers, json={'public_key':item['public_key']}).status_code == 409


@pytest.mark.parametrize('change', [
    {'public_key':'A'*44}, {'public_key':base64.b64encode(bytes(32)).decode()},
    {'public_key':base64.b64encode((1).to_bytes(32,'little')).decode()},
    {'public_key':base64.b64encode((2**255-19).to_bytes(32,'little')).decode()},
    {'public_key':base64.b64encode(bytes([255])*32).decode()}, {'public_key':3},
    {'private_key':'sensitive-sentinel'}, {'device_id':'other'}, {'state':'approved'},
    {'gateway_state':'applied'}, {'allowed_ips':['0.0.0.0/0']}, {'interface':'wg0; touch bad'},
])
def test_invalid_or_privileged_input_rejected_without_echo(lab, change):
    result = lab[1].post(CLIENT, json={'public_key':key(), **change})
    assert result.status_code == 422
    assert 'sensitive-sentinel' not in result.text
    assert lab[0].get(ADMIN).json()['enrollments'] == []


def test_changed_key_stale_decision_and_revival_rejected(lab):
    item = request(lab)
    assert lab[1].post(CLIENT,json={'public_key':key()}).status_code == 409
    approved = approve(lab,item).json()
    assert approve(lab,item).status_code == 409
    revoked = lab[0].post(ADMIN+'/'+item['device_id'],json={'revision':approved['revision'],'approve':False})
    assert revoked.status_code == 200 and revoked.json()['state'] == 'revoked'
    assert request(lab,item['public_key'])['state'] == 'revoked'
    assert approve(lab,revoked.json()).status_code == 409


@pytest.mark.parametrize('cause',['device','logout','refresh_reuse','member','expired'])
def test_revocation_paths_invalidate_enrollment(lab,cause):
    admin, client, service, tokens = lab
    item = request(lab); assert approve(lab,item).status_code == 200
    if cause=='device': service.revoke(tokens['device_id'])
    elif cause=='logout': assert client.post('/api/v1/device/logout',json={}).status_code == 200
    elif cause=='refresh_reuse':
        service.refresh(tokens['refresh_token'])
        with pytest.raises(DeviceError): service.refresh(tokens['refresh_token'])
    elif cause=='member':
        with service.store._db() as db:
            db.execute("INSERT INTO member_accounts(subject,username,disabled) VALUES('member','alice',0)")
            db.execute("UPDATE devices SET account_id='member' WHERE id=?",(tokens['device_id'],))
        Members(service.store,'http://unused').revoke('member')
    else:
        with service.store._db() as db: db.execute('UPDATE devices SET expires_at=0 WHERE id=?',(tokens['device_id'],))
    assert client.get(CLIENT).status_code == 401
    assert client.post(CLIENT,json={'public_key':item['public_key']}).status_code == 401
    items = admin.get(ADMIN).json()['enrollments']
    if cause == 'expired':
        assert items == []  # Device housekeeping also removes its uninstalled enrollment.
        assert approve(lab,item).status_code == 404
    else:
        assert items[0]['state'] == 'revoked'
        assert approve(lab,items[0]).status_code == 409


def test_enrollment_revoked_on_snapshot_restore(tmp_path):
    store=state_fixture(tmp_path); service=Devices(store); tokens=associate(service)
    enrollment=WireGuardEnrollments(store)
    item=enrollment.request(tokens['access_token'],key()); enrollment.decide(item['device_id'],1,True)
    revoke_restored_sessions(tmp_path)
    assert enrollment.list()[0]['state']=='revoked'
    with pytest.raises(DeviceError): enrollment.status(tokens['access_token'])
    with store._db() as db:
        assert db.execute('SELECT state,revision FROM wireguard_enrollments').fetchone()==('revoked',3)


def test_revoke_racing_with_enrollment_cannot_leave_live_request(lab):
    _,_,service,tokens=lab; public=key()
    def enroll():
        try: return WireGuardEnrollments(Store(service.store.dir)).request(tokens['access_token'],public)
        except DeviceError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(enroll); two=pool.submit(service.revoke,tokens['device_id']); one.result(); two.result()
    assert all(item['state']=='revoked' for item in WireGuardEnrollments(service.store).list())


def test_existing_schema_three_without_enrollment_table_upgrades_additively(lab):
    _,_,service,tokens=lab
    with service.store._db() as db: db.execute('DROP TABLE wireguard_enrollments')
    upgraded=Store(service.store.dir)
    assert Devices(upgraded).authenticate(tokens['access_token'])['device_id']==tokens['device_id']
    assert WireGuardEnrollments(upgraded).list()==[]


def test_simultaneous_first_starts_share_atomic_schema_and_identity(tmp_path):
    for attempt in range(8):
        folder=tmp_path/str(attempt); barrier=threading.Barrier(6)
        def start(_):
            barrier.wait(timeout=10)
            store=Store(folder)
            return Devices(store).identity()
        with ThreadPoolExecutor(max_workers=6) as pool:
            identities=list(pool.map(start,range(6)))
        assert len(set(identities))==1
        with Store(folder)._db() as db:
            assert {'account_id','account_name','directory_entry'}.issubset(
                row[1] for row in db.execute('PRAGMA table_info(devices)'))


def test_cold_start_waits_for_journal_lock_without_losing_identity(tmp_path):
    folder=tmp_path/'nova'; folder.mkdir(); entered=threading.Event()
    with sqlite3.connect(folder/'nova.sqlite3') as blocking:
        blocking.execute('BEGIN IMMEDIATE')
        def start():
            entered.set()
            return Devices(Store(folder)).identity()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(start); assert entered.wait(5)
            time.sleep(.15)
            premature=future.done()
            blocking.commit()
            identity=future.result(timeout=10)
        assert not premature
        assert Devices(Store(folder)).identity()==identity
