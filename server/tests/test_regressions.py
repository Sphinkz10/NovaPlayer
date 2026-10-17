"""Behavioural regressions for the October audit, including concurrent workers."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest
from fastapi.testclient import TestClient
from nova_server.app import make_app
from nova_server.jellyfin import probe_jellyfin, MAX_INFO_BYTES
from nova_server.storage import Store
from test_api import bootstrap, login, PASS


def test_concurrent_wrong_logins_are_reserved_before_verification(test_client):
    client, _ = test_client
    bootstrap(client)
    start = Barrier(12)
    def attempt(_):
        start.wait(timeout=10)
        return login(client, password='wrong').status_code
    with ThreadPoolExecutor(max_workers=12) as pool:
        statuses = list(pool.map(attempt, range(12)))
    assert sorted(statuses) == [401] * 5 + [429] * 7
    assert login(client, password=PASS).status_code == 429


def test_login_reservations_are_atomic_across_store_instances(tmp_path):
    stores = [Store(tmp_path) for _ in range(12)]
    start = Barrier(12)
    def reserve(store):
        start.wait(timeout=10)
        return store.reserve_login_attempt('source')
    with ThreadPoolExecutor(max_workers=12) as pool:
        reservations = list(pool.map(reserve, stores))
    accepted = [value for value in reservations if value is not None]
    assert len(accepted) == len(set(accepted)) == 5
    stores[0].complete_successful_login(accepted[0])
    assert stores[1].reserve_login_attempt('source') is not None
    assert stores[2].reserve_login_attempt('source') is None
    assert stores[2].reserve_login_attempt('different-source') is not None


def test_expired_reservations_no_longer_block(tmp_path, monkeypatch):
    now = 1000
    monkeypatch.setattr('nova_server.storage.time.time', lambda: now)
    store = Store(tmp_path)
    for _ in range(5):
        assert store.reserve_login_attempt('source') is not None
    assert store.reserve_login_attempt('source') is None
    now += 900
    assert store.reserve_login_attempt('source') is not None


def test_success_does_not_erase_previous_failed_attempts(test_client):
    client, _ = test_client
    bootstrap(client)
    for _ in range(4):
        assert login(client, password='wrong').status_code == 401
    assert login(client).status_code == 200
    assert login(client, password='wrong').status_code == 401
    assert login(client).status_code == 429


def test_untrusted_hosts_rejected_by_default(tmp_path):
    with TestClient(make_app(state_dir=tmp_path), base_url='http://localhost') as client:
        assert client.get('/api/v1/health/live').status_code == 200
        assert client.get('/', headers={'Host': 'attacker.example'}).status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'ProductName': 'Different Product'}, {'ProductName': None},
    {'StartupWizardCompleted': None}, {'StartupWizardCompleted': 'false'},
    {'StartupWizardCompleted': 1}, {'Id': '   '}, {'Id': 'x' * 257},
])
async def test_false_ready_responses_rejected(changes):
    payload = {'Id': 'server', 'ProductName': 'Jellyfin', 'StartupWizardCompleted': True, **changes}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    assert (await probe_jellyfin('http://jellyfin', transport))['state'] == 'invalid_response'


@pytest.mark.asyncio
async def test_pinned_identity_is_checked_before_readiness():
    payload = {'Id': 'server', 'ProductName': 'Jellyfin', 'StartupWizardCompleted': True}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    assert (await probe_jellyfin('http://jellyfin', transport, expected_server_id='other'))['state'] == 'identity_mismatch'
    result = await probe_jellyfin('http://jellyfin', transport, expected_server_id='server')
    assert result['state'] == 'ready' and result['identity_verified'] is True


@pytest.mark.asyncio
async def test_probe_stops_reading_oversized_stream():
    class Oversized(httpx.AsyncByteStream):
        chunks_read = 0
        closed = False
        async def __aiter__(self):
            for _ in range(100):
                self.chunks_read += 1
                yield b'x' * 4096
        async def aclose(self):
            self.closed = True
    stream = Oversized()
    transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    assert (await probe_jellyfin('http://jellyfin', transport))['state'] == 'invalid_response'
    assert stream.chunks_read == MAX_INFO_BYTES // 4096 + 1
    assert stream.closed


@pytest.mark.asyncio
async def test_probe_total_deadline(monkeypatch):
    class Slow(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(.01)
                yield b' '
        async def aclose(self):
            self.closed = True
    stream = Slow()
    monkeypatch.setattr('nova_server.jellyfin.PROBE_TIMEOUT', .05)
    transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    assert (await probe_jellyfin('http://jellyfin', transport))['state'] == 'timeout'
    assert stream.closed


@pytest.mark.asyncio
async def test_probe_refuses_compression_before_reading_body():
    class Unreadable(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError('Compressed response must not be read or decompressed')
            yield b''
    def respond(request):
        assert request.headers['Accept-Encoding'] == 'identity'
        return httpx.Response(200, headers={'Content-Encoding':'gzip'}, stream=Unreadable())
    result = await probe_jellyfin('http://jellyfin', httpx.MockTransport(respond))
    assert result['state'] == 'invalid_response'
