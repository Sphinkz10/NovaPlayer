import pytest
import sqlite3

TOKEN='unit-'+'x'*60
PASS='long-passphrase-at-least-14'

def bootstrap(client,username='owner',password=PASS,token=TOKEN):
    return client.post('/api/v1/admin/bootstrap',json={'username':username,'password':password},headers={'X-NOVA-Bootstrap':token})

def login(client,password=PASS,username='owner'):
    return client.post('/api/v1/admin/login',json={'username':username,'password':password})

def test_health_is_local_only_policy(test_client):
    client,_=test_client
    assert client.get('/api/v1/health/live').json()=={'status':'up','component':'nova-core'}
    data=client.get('/api/v1/status').json()
    assert data['owner_setup_required'] is True
    assert data['remote_access_enabled'] is False
    assert data['directory_enabled'] is False

def test_first_owner_with_secret(test_client):
    client,state=test_client
    r=bootstrap(client)
    assert r.status_code==201
    assert r.json()['admin']=='owner'
    assert not (state/'bootstrap.token').exists()
    assert client.get('/api/v1/status').json()['owner_setup_required'] is False
    assert bootstrap(client).status_code==409

def test_bootstrap_secret_required(test_client):
    client,state=test_client
    for token in ('','invalid','unit-'+ 'y'*60):
        assert bootstrap(client,token=token).status_code==403
    assert (state/'bootstrap.token').exists()

def test_bootstrap_bad_username(test_client):
    client,_=test_client
    assert bootstrap(client,username='../../hello').status_code==422
    assert bootstrap(client,username='qq').status_code==422

def test_bootstrap_short_password(test_client):
    client,_=test_client
    assert bootstrap(client,password='short').status_code==422

def test_bootstrap_max_password_length(test_client):
    client,_=test_client
    assert bootstrap(client,password='q'*1025).status_code==422

def test_admin_hashed_at_rest_and_no_plaintext(test_client):
    client,state=test_client
    assert bootstrap(client).status_code==201
    text=(state/'nova.sqlite3').read_bytes()
    assert PASS.encode() not in text
    with sqlite3.connect(state/'nova.sqlite3') as con:
        hashed=con.execute('SELECT password_hash FROM admin WHERE id=1').fetchone()[0]
    assert hashed.startswith('$argon2id$')

def test_login_and_overview_authorization(test_client,monkeypatch):
    client,_=test_client
    assert bootstrap(client).status_code==201
    assert client.get('/api/v1/admin/overview').status_code==401
    assert client.get('/api/v1/admin/overview',headers={'Authorization':'Bearer wrong'}).status_code==401
    async def fake(_):
        return {'state':'ready','server_id':'abcd','version':'12.2'}
    monkeypatch.setattr('nova_server.app.probe_jellyfin',fake)
    r=login(client)
    assert r.status_code==200
    tok=r.json()['access_token']
    assert len(tok)>=48
    response=client.get('/api/v1/admin/overview',headers={'Authorization':'Bearer '+tok})
    assert response.status_code==200
    data=response.json()
    assert data['jellyfin']['state']=='ready'
    assert data['connect']['state']=='disabled'
    assert all(root['read_only'] for root in data['library_roots'])
    assert response.headers['cache-control']=='no-store'
    assert response.headers['x-frame-options']=='DENY'
    assert 'frame-ancestors' in response.headers['content-security-policy']
    assert 'sqlite' not in response.text
    assert 'token' not in response.text
    assert client.post('/api/v1/admin/logout',headers={'Authorization':'Bearer '+tok}).status_code==200
    assert client.get('/api/v1/admin/overview',headers={'Authorization':'Bearer '+tok}).status_code==401

def test_no_admin_login(test_client):
    client,_=test_client
    assert login(client).status_code==401

def test_failed_password_no_information_leak(test_client):
    client,_=test_client
    bootstrap(client)
    a=login(client,username='noexist').json()
    b=login(client,password='wrong').json()
    assert a==b=={'detail':'Credenciais inválidas.'}

def test_login_rate_limits(test_client):
    client,_=test_client;bootstrap(client)
    for _ in range(5):assert login(client,password='wrong').status_code==401
    assert login(client,password=PASS).status_code==429

def test_bootstrap_race_fail_closed(test_client):
    client,_=test_client
    assert bootstrap(client).status_code==201
    assert bootstrap(client,username='attacker',password=PASS).status_code==409
    assert login(client,username='attacker').status_code==401

def test_session_token_not_stored(test_client):
    client,state=test_client;bootstrap(client)
    token=login(client).json()['access_token']
    assert token.encode() not in (state/'nova.sqlite3').read_bytes()

def test_headers_on_errors_and_page(test_client):
    client,_=test_client
    for path in ['/','/api/v1/admin/overview','/not-found']:
        r=client.get(path)
        assert 'nosniff' == r.headers['x-content-type-options']
        assert r.headers['referrer-policy']=='no-referrer'
        assert 'default-src' in r.headers['content-security-policy']
    assert 'https://' not in client.get('/').text

def test_static_js_does_not_persist_token(test_client):
    client,_=test_client
    response=client.get('/static/control.js')
    assert response.status_code==200
    assert 'localStorage.setItem' not in response.text
    assert 'eval(' not in response.text
