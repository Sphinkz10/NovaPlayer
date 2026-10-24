import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from nova_server.setup import Credentials, JellyfinSetup, SetupError, SetupRequest
from nova_server.storage import Store


PASSWORD = 'synthetic-jellyfin-password'
PAYLOAD = dict(username='owner', password=PASSWORD, libraries=[
    dict(name='Filmes', collection_type='movies', roots=['source-a', 'source-b'])])


class Jellyfin:
    def __init__(self):
        self.completed = False
        self.password_set = False
        self.libraries = []
        self.calls = []
        self.sid = 'server1'
        self.fail_once = None
        self.admin = True

    def handle(self, request):
        path = request.url.path
        self.calls.append((request.method, path))
        if path == self.fail_once:
            self.fail_once = None
            return httpx.Response(500)
        if path == '/System/Info/Public':
            data = {'ProductName': 'Jellyfin Server', 'Id': self.sid,
                    'StartupWizardCompleted': self.completed}
        elif path == '/Users/AuthenticateByName':
            if not self.password_set:
                return httpx.Response(401)
            data = {'AccessToken': 'ephemeralSecret123', 'ServerId': self.sid,
                    'User': {'Policy': {'IsAdministrator': self.admin}}}
        elif path == '/Startup/User':
            if request.method == 'POST':
                assert not self.password_set, 'Never overwrite a password on retry'
                self.password_set = True
            data = {'Name': 'owner'}
        elif path == '/Library/VirtualFolders':
            if request.method == 'POST':
                body = json.loads(request.content)
                self.libraries.append({'Name': request.url.params['name'],
                    'CollectionType': request.url.params['collectionType'],
                    'Locations': [p['Path'] for p in body['LibraryOptions']['PathInfos']],
                    'ItemId': str(len(self.libraries)+1)})
                return httpx.Response(204)
            data = self.libraries
        elif path == '/Items':
            data = {'TotalRecordCount': 2}
        elif path == '/Startup/Complete':
            self.completed = True
            return httpx.Response(204)
        else:
            data = None
        if path not in ('/System/Info/Public', '/Startup/User', '/Users/AuthenticateByName'):
            assert ', Token="ephemeralSecret123"' in request.headers.get('Authorization', '')
            assert 'X-Emby-Token' not in request.headers
        return httpx.Response(200, json=data) if data is not None else httpx.Response(204)


def service(tmp_path, fake):
    store = Store(tmp_path)
    return JellyfinSetup(store, 'http://jellyfin:8096', transport=httpx.MockTransport(fake.handle))


def run(setup, configure=True):
    payload = SetupRequest(**PAYLOAD) if configure else Credentials(username='owner', password=PASSWORD)
    return asyncio.run(setup.run(payload, configure=configure))


def test_setup_retry_verify_and_no_saved_credentials(tmp_path):
    fake = Jellyfin()
    setup = service(tmp_path, fake)
    report = run(setup)
    assert report['libraries'][0]['indexed_items'] == 2
    assert report['read_only_verified'] is None
    assert not setup.store.setup_state()['busy']
    run(setup)
    assert len(fake.libraries) == 1
    assert fake.calls.count(('POST', '/Startup/User')) == 1
    assert fake.calls.count(('POST', '/Sessions/Logout')) == 2
    assert run(setup, configure=False)['indexing_requested'] is False
    assert Store(tmp_path).setup_state()['last_observation']['server_id'] == 'server1'
    for file in tmp_path.iterdir():
        assert PASSWORD.encode() not in file.read_bytes()
        assert b'ephemeralSecret123' not in file.read_bytes()


@pytest.mark.parametrize('failure', ['/Startup/Configuration', '/Startup/Complete', '/Library/Refresh'])
def test_resume_after_partial_write(tmp_path, failure):
    fake = Jellyfin()
    fake.fail_once = failure
    setup = service(tmp_path, fake)
    with pytest.raises(SetupError):
        run(setup)
    assert not setup.store.setup_state()['busy']
    run(setup)
    assert fake.calls.count(('POST', '/Startup/User')) == 1
    assert len(fake.libraries) == 1


def test_identity_pinned_before_sending_credentials(tmp_path):
    fake = Jellyfin()
    setup = service(tmp_path, fake)
    run(setup)
    fake.sid = 'different-server'
    fake.calls.clear()
    with pytest.raises(SetupError, match='identity_changed'):
        run(setup)
    assert fake.calls == [('GET', '/System/Info/Public')]


def test_cross_store_lease(tmp_path):
    first, second = Store(tmp_path), Store(tmp_path)
    assert first.acquire_setup('one')
    assert not second.acquire_setup('two')
    second.finish_setup('two')
    assert first.setup_state()['busy']
    first.finish_setup('one')
    assert second.acquire_setup('two')


def test_conflict_does_not_modify_existing_libraries(tmp_path):
    fake = Jellyfin()
    fake.libraries = [{'Name': 'Existing', 'ItemId': '1', 'CollectionType': 'movies',
                       'Locations': ['/media/source-a']}]
    with pytest.raises(SetupError, match='library_conflict'):
        run(service(tmp_path, fake))
    assert ('POST', '/Library/VirtualFolders') not in fake.calls


def test_reject_non_admin_and_revoke_token(tmp_path):
    fake = Jellyfin()
    fake.completed = fake.password_set = True
    fake.admin = False
    with pytest.raises(SetupError, match='admin_required'):
        run(service(tmp_path, fake))
    assert fake.calls[-1] == ('POST', '/Sessions/Logout')
    assert not fake.libraries


@pytest.mark.parametrize('libraries', [
    [{'name': 'Films', 'roots': ['source-a']}],
    [{'name': 'Films', 'roots': ['source-a', 'source-a']}],
    [{'name': '../Films', 'roots': ['source-a', 'source-b']}],
    [{'name': 'Films', 'roots': ['/etc', 'source-b']}],
    [{'name': 'Same', 'roots': ['source-a']}, {'name': 'same', 'roots': ['source-b']}],
])
def test_reject_invalid_library_layout(libraries):
    with pytest.raises(ValidationError):
        SetupRequest(**{**PAYLOAD, 'libraries': libraries})


def test_api_auth_and_password_not_reflected(test_client):
    client, state = test_client
    assert client.get('/api/v1/admin/setup').status_code == 401
    assert client.post('/api/v1/admin/setup/jellyfin', json=PAYLOAD).status_code == 401
    account = {'username': 'owner', 'password': 'synthetic-nova-password'}
    assert client.post('/api/v1/admin/bootstrap', json=account,
                       headers={'X-NOVA-Bootstrap': 'unit-'+'x'*60}).status_code == 201
    headers = {'Authorization': 'Bearer '+client.post('/api/v1/admin/login', json=account).json()['access_token']}
    response = client.post('/api/v1/admin/setup/jellyfin', headers=headers,
                           json={**PAYLOAD, 'password': PASSWORD*100})
    assert response.status_code == 422
    assert PASSWORD not in response.text
    fake = Jellyfin()
    client.app.state.jellyfin_setup.transport = httpx.MockTransport(fake.handle)
    assert client.post('/api/v1/admin/setup/jellyfin', headers=headers, json=PAYLOAD).status_code == 200
    assert client.get('/api/v1/admin/setup', headers=headers).json()['last_observation']['wizard_completed']
