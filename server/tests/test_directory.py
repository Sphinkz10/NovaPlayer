from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import sqlite3
import uuid

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.exceptions import InvalidSignature
from fastapi.testclient import TestClient

from nova_directory.api import make_directory
from nova_directory.client import server_identity
from nova_directory.protocol import ChallengeRequest, Descriptor, Proof, encode, message, verify_record
from nova_directory.store import Registry, DirectoryError
from nova_server.storage import Store

ORIGIN = 'https://127.0.0.1:9443'
PASSWORD = 'disposable-directory-password'


def certificate(now=None, *, host='127.0.0.1', days=1, san=True):
    now = now or datetime.now(timezone.utc)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, 'NOVA disposable')])
    builder = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
        .not_valid_after(now+timedelta(days=days)))
    if san:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host))]), critical=False)
    return builder.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode(), key


@pytest.fixture
def registry(tmp_path):
    clock = [int(datetime.now(timezone.utc).timestamp())]
    registry = Registry(tmp_path/'directory', ORIGIN, lambda: clock[0])
    # Identity/authorization tests don't need to repeat expensive password hashing.
    owner, guest, stranger = (str(uuid.uuid4()) for _ in range(3))
    with registry.db() as db:
        for identity, name in ((owner,'owner'),(guest,'guest'),(stranger,'stranger')):
            db.execute('INSERT INTO accounts(id,username,password_hash) VALUES(?,?,?)', (identity,name,'unused'))
    registry.clock_fixture = clock
    registry.actors = owner, guest, stranger
    return registry


def request():
    cert, _ = certificate()
    key = ed25519.Ed25519PrivateKey.generate()
    return key, ChallengeRequest(public_key=encode(key.public_key().public_bytes_raw()), descriptor=Descriptor(
        server_id=str(uuid.uuid4()), name='Casa', client_origin='https://127.0.0.1:8920', certificate_pem=cert))


def signed(registry, owner, key, req):
    payload = registry.challenge(owner, req)
    return payload, Proof(challenge_id=payload['challenge_id'], signature=encode(key.sign(message(payload))))


def registered(registry):
    key, req = request()
    p, proof = signed(registry, registry.actors[0], key, req)
    record = registry.register(registry.actors[0], proof)
    return key, req, p, proof, record


def test_registration_discovery_membership_revocation_and_restart(registry):
    owner, guest, stranger = registry.actors
    key, req, p, proof, record = registered(registry)
    assert verify_record(record, ORIGIN).server_id == req.descriptor.server_id
    assert registry.discover(guest) == registry.discover(stranger) == []
    assert registry.discover(owner)[0]['record'] == record
    registry.membership(owner, p['entry_id'], 'guest', True)
    reopened = Registry(registry.root, ORIGIN)
    assert reopened.discover(guest)[0]['record'] == record
    with pytest.raises(DirectoryError):
        registry.membership(guest, p['entry_id'], 'stranger', True)
    with pytest.raises(DirectoryError):
        registry.remove(stranger, p['entry_id'])
    registry.membership(owner, p['entry_id'], 'guest', False)
    assert registry.discover(guest) == []
    registry.remove(owner, p['entry_id'])
    assert registry.discover(owner) == []
    with pytest.raises(DirectoryError):
        registry.challenge(owner, req)


def test_bad_signature_consumes_challenge_and_cannot_replay(registry):
    owner = registry.actors[0]; key, req = request()
    p, proof = signed(registry, owner, key, req)
    bad = proof.model_copy(update={'signature':encode(b'x'*64)})
    with pytest.raises(DirectoryError) as error:
        registry.register(owner, bad)
    assert error.value.code == 'invalid_proof'
    with pytest.raises(DirectoryError) as error:
        registry.register(owner, proof)
    assert error.value.code == 'invalid_challenge'
    assert registry.discover(owner) == []


def test_proof_is_bound_to_account_not_another_account(registry):
    owner, guest, _ = registry.actors; key, req = request()
    p, proof = signed(registry, owner, key, req)
    with pytest.raises(DirectoryError):
        registry.register(guest, proof)
    assert registry.register(owner, proof)['payload'] == p


def test_proof_expires_and_registration_replay_fails(registry):
    owner = registry.actors[0]; key, req = request()
    p, proof = signed(registry, owner, key, req)
    registry.clock_fixture[0] += 60
    with pytest.raises(DirectoryError):
        registry.register(owner, proof)
    p, proof = signed(registry, owner, key, req)
    registry.register(owner, proof)
    with pytest.raises(DirectoryError):
        registry.register(owner, proof)


def test_concurrent_proof_only_one_success_across_store_instances(registry):
    owner = registry.actors[0]; key, req = request()
    p, proof = signed(registry, owner, key, req)
    def submit(_):
        try:
            Registry(registry.root, ORIGIN).register(owner, proof); return True
        except DirectoryError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(submit, range(4))) == 1


def test_stale_concurrent_update_cannot_overwrite_newer_record(registry):
    owner = registry.actors[0]; key, req, p, _, _ = registered(registry)
    first, proof1 = signed(registry, owner, key, req)
    changed = req.model_copy(update={'descriptor':req.descriptor.model_copy(update={'name':'Updated'})})
    _, proof2 = signed(registry, owner, key, changed)
    registry.register(owner, proof2)
    with pytest.raises(DirectoryError) as error:
        registry.register(owner, proof1)
    assert error.value.code == 'stale_challenge'
    assert registry.discover(owner)[0]['record']['payload']['descriptor']['name'] == 'Updated'


def test_first_registration_race_only_one_entry(registry):
    owner = registry.actors[0]; key, req = request()
    _, a = signed(registry, owner, key, req)
    _, b = signed(registry, owner, key, req)
    registry.register(owner, a)
    with pytest.raises(DirectoryError):
        registry.register(owner, b)
    assert len(registry.discover(owner)) == 1


def test_key_replacement_forbidden_and_server_uuid_scoped_to_owner(registry):
    owner, guest, _ = registry.actors
    key, req, _, _, _ = registered(registry)
    other = ed25519.Ed25519PrivateKey.generate()
    changed = req.model_copy(update={'public_key':encode(other.public_key().public_bytes_raw())})
    with pytest.raises(DirectoryError):
        registry.challenge(owner, changed)
    _, proof = signed(registry, guest, other, changed)
    registry.register(guest, proof)
    assert len(registry.discover(owner)) == len(registry.discover(guest)) == 1
    assert registry.discover(owner)[0]['record']['payload']['public_key'] == req.public_key


def test_old_challenge_cannot_resurrect_deleted_entry(registry):
    owner = registry.actors[0]; key, req, p, _, _ = registered(registry)
    _, proof = signed(registry, owner, key, req)
    registry.remove(owner, p['entry_id'])
    with pytest.raises(DirectoryError):
        registry.register(owner, proof)
    assert registry.discover(owner) == []


def test_lease_expires_then_same_key_can_renew(registry):
    owner = registry.actors[0]; key, req, _, _, record = registered(registry)
    registry.clock_fixture[0] += 3600
    assert registry.discover(owner) == []
    with pytest.raises(ValueError):
        verify_record(record, ORIGIN, now=registry.clock())
    _, proof = signed(registry, owner, key, req)
    registry.register(owner, proof)
    assert registry.discover(owner)[0]['record']['payload']['version'] == 2


@pytest.mark.parametrize('field,value', [('audience','https://127.0.0.1:9444'), ('owner_id',str(uuid.uuid4())),
    ('entry_id',str(uuid.uuid4())), ('version',2), ('expires_at',4000000000), ('purpose','media')])
def test_signed_fields_cannot_be_changed(registry, field, value):
    record = registered(registry)[-1]
    record['payload'][field] = value
    with pytest.raises((ValueError,InvalidSignature)):
        verify_record(record, ORIGIN)


def test_descriptor_tamper_wrong_key_and_wrong_audience_rejected(registry):
    key, req, _, _, record = registered(registry)
    with pytest.raises(ValueError):
        verify_record(record, ORIGIN, expected_key=encode(b'x'*32))
    with pytest.raises(ValueError):
        verify_record(record, 'https://127.0.0.1:9999')
    record['payload']['descriptor']['client_origin'] = 'https://127.0.0.1:8000'
    with pytest.raises(InvalidSignature):
        verify_record(record, ORIGIN)


@pytest.mark.parametrize('origin', ['http://127.0.0.1:8920','https://8.8.8.8:443','https://127.0.0.1:8920/path',
    'https://user@127.0.0.1:8920','https://127.0.0.1:8920?token=secret','https://localhost:8920'])
def test_public_or_noncanonical_endpoint_rejected(origin):
    _, req = request()
    data = req.descriptor.model_dump(); data['client_origin'] = origin
    with pytest.raises(ValueError):
        Descriptor.model_validate(data)


@pytest.mark.parametrize('kind', ['hostname','expired','future','missing-san','private-key'])
def test_invalid_tls_identity_rejected(registry, kind):
    key, req = request()
    now = datetime.now(timezone.utc)
    if kind == 'hostname': pem, _ = certificate(host='10.0.0.1')
    elif kind == 'expired': pem, _ = certificate(now-timedelta(days=2))
    elif kind == 'future': pem, _ = certificate(now+timedelta(days=2))
    elif kind == 'missing-san': pem, _ = certificate(san=False)
    else: pem = key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    data = req.model_dump(); data['descriptor']['certificate_pem'] = pem
    with pytest.raises((ValueError,DirectoryError)):
        registry.challenge(registry.actors[0], ChallengeRequest.model_validate(data))


def test_disabled_owner_hides_entries_from_members_and_blocks_pending_proof(registry):
    owner, guest, _ = registry.actors; key, req, p, _, _ = registered(registry)
    registry.membership(owner, p['entry_id'],'guest',True)
    _, proof = signed(registry, owner,key,req)
    registry.disable_account('owner')
    assert registry.discover(guest) == []
    with pytest.raises(DirectoryError): registry.register(owner,proof)
    with pytest.raises(DirectoryError): registry.discover(owner)


def test_challenge_and_source_limits_persist_after_rejection(registry):
    key, req = request(); owner = registry.actors[0]
    for _ in range(8): registry.challenge(owner,req)
    with pytest.raises(DirectoryError): registry.challenge(owner,req)
    for _ in range(3): registry.limit('test','source',3,100)
    for _ in range(2):
        with pytest.raises(DirectoryError): Registry(registry.root,ORIGIN).limit('test','source',3,100)
    registry.clock_fixture[0] += 901
    registry.challenge(owner,req)
    registry.limit('test','source',3,100)


def test_account_passwords_sessions_expiry_logout_and_disable(tmp_path):
    clock = [int(datetime.now(timezone.utc).timestamp())]
    registry = Registry(tmp_path,ORIGIN,lambda:clock[0])
    identity = registry.create_account('owner',PASSWORD)
    with registry.db() as db:
        value = db.execute('SELECT password_hash FROM accounts').fetchone()[0]
    assert value.startswith('$argon2id$') and PASSWORD not in value
    result = registry.login('owner',PASSWORD,'source')
    assert registry.authenticate(result['access_token']) == identity
    with registry.db() as db:
        assert result['access_token'] not in str([tuple(r) for r in db.execute('SELECT * FROM sessions')])
    registry.logout(result['access_token'])
    with pytest.raises(DirectoryError): registry.authenticate(result['access_token'])
    second = registry.login('owner',PASSWORD,'source')['access_token']
    clock[0] += 901
    with pytest.raises(DirectoryError): registry.authenticate(second)
    third = registry.login('owner',PASSWORD,'source')['access_token']
    registry.disable_account('owner')
    with pytest.raises(DirectoryError): registry.authenticate(third)
    for name, password in [('owner',PASSWORD),('missing',PASSWORD),('owner','wrong')]:
        with pytest.raises(DirectoryError) as error: registry.login(name,password,'source')
        assert error.value.code == 'invalid_credentials'


def test_api_https_auth_separation_validation_no_secret_echo_and_limits(tmp_path):
    app = make_directory(tmp_path,ORIGIN)
    registry = app.state.registry; registry.create_account('owner',PASSWORD)
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.get('/api/v1/directory/servers').status_code == 401
        assert client.get('http://127.0.0.1:9443/api/v1/directory/health',headers={'X-Forwarded-Proto':'https'}).status_code == 400
        response = client.post('/api/v1/directory/login',json={'username':'owner','password':PASSWORD,'extra':'secret'})
        assert response.status_code == 422 and PASSWORD not in response.text and 'secret' not in response.text
        assert client.post('/api/v1/directory/login',content=b'x'*8193).status_code == 413
        assert client.post('/api/v1/directory/login',content=(b'x'*3000 for _ in range(3))).status_code == 413
        token = client.post('/api/v1/directory/login',json={'username':'owner','password':PASSWORD}).json()['access_token']
        client.headers['Authorization'] = 'Bearer '+token
        response = client.get('/api/v1/directory/servers')
        assert response.json() == {'servers':[], 'media_authorized':False}
        assert response.headers['cache-control'] == 'no-store'
        for path in ('/api/v1/admin/overview','/api/v1/device/me','/Users','/docs','/api/v1/directory/signup'):
            assert client.get(path).status_code == 404
        assert client.get('/api/v1/directory/health',headers={'Host':'attacker.test'}).status_code == 400
        assert client.post('/api/v1/directory/logout').status_code == 200
        assert client.get('/api/v1/directory/servers').status_code == 401


def test_server_key_explicit_creation_persistence_and_separation(tmp_path, monkeypatch):
    store = Store(tmp_path/'nova'); store.bootstrap('owner','unused')
    connections = []
    connect = sqlite3.connect
    def tracked_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection
    monkeypatch.setattr('nova_directory.client.sqlite3.connect', tracked_connect)
    with pytest.raises(FileNotFoundError): server_identity(store.dir)
    sid, key = server_identity(store.dir,create_key=True)
    again, other = server_identity(store.dir)
    assert sid == again and key.public_key().public_bytes_raw() == other.public_key().public_bytes_raw()
    signature = key.sign(b'proof')
    other.public_key().verify(signature,b'proof')
    assert not (store.dir/'directory.sqlite3').exists()
    (store.dir/'directory-signing.key').write_bytes(b'corrupted')
    with pytest.raises(ValueError): server_identity(store.dir,create_key=True)
    # Retaining references prevents garbage collection from hiding a leaked handle.
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            connection.execute('SELECT 1')


def test_refuse_future_directory_schema(tmp_path):
    with sqlite3.connect(tmp_path/'directory.sqlite3') as db: db.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError): Registry(tmp_path,ORIGIN)


@pytest.mark.parametrize('field', ['media_titles','history','vpn_key','jellyfin_token','password'])
def test_descriptor_rejects_media_and_secret_fields(field):
    _, req = request()
    raw = req.descriptor.model_dump(); raw[field] = 'must-not-be-stored'
    with pytest.raises(ValueError): Descriptor.model_validate(raw)


def test_login_budget_reserved_before_password_verification(registry, monkeypatch):
    attempts = []
    monkeypatch.setattr('nova_directory.store.verify_password', lambda *args: attempts.append(1) or False)
    for _ in range(10):
        with pytest.raises(DirectoryError) as error: registry.login('owner','wrong','same-origin')
        assert error.value.status == 401
    with pytest.raises(DirectoryError) as error: registry.login('owner','wrong','same-origin')
    assert error.value.status == 429 and len(attempts) == 10


def test_membership_idempotent_and_owner_cannot_remove_itself(registry):
    owner, guest, _ = registry.actors; _, _, p, _, _ = registered(registry)
    for _ in range(3): registry.membership(owner,p['entry_id'],'guest',True)
    assert len(registry.discover(guest)) == 1
    with pytest.raises(DirectoryError): registry.membership(owner,p['entry_id'],'owner',False)
    for _ in range(3): registry.membership(owner,p['entry_id'],'guest',False)
    assert registry.discover(guest) == []


def test_changed_certificate_requires_fresh_signature_and_preserves_key(registry):
    owner = registry.actors[0]; key, req, p, _, record = registered(registry)
    pem, _ = certificate()
    changed = ChallengeRequest(public_key=req.public_key, descriptor=Descriptor(
        **{**req.descriptor.model_dump(), 'certificate_pem':pem}))
    payload, proof = signed(registry,owner,key,changed)
    updated = registry.register(owner,proof)
    assert updated['payload']['entry_id'] == p['entry_id'] and updated['payload']['version'] == 2
    assert verify_record(updated,ORIGIN,expected_key=req.public_key).certificate_pem == pem
    assert record['payload']['descriptor']['certificate_pem'] != pem
