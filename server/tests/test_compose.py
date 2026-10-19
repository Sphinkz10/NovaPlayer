from pathlib import Path
import yaml

ROOT=Path(__file__).parents[1]

def services():
    return yaml.safe_load((ROOT/'compose.yaml').read_text())['services']

def test_compose_two_services():
    s=services();assert set(s)=={'nova-core','jellyfin'}

def test_ports_loopback():
    for service in services().values():
        for port in service.get('ports',[]):
            assert port.startswith('127.0.0.1:'),port

def test_no_host_or_privileged():
    for s in services().values():
        assert s.get('privileged') is not True
        assert s.get('network_mode')!='host'
        assert 'ALL' in s['cap_drop']
        assert 'no-new-privileges:true' in s['security_opt']

def test_media_read_only():
    media=[p for p in services()['jellyfin']['volumes'] if isinstance(p,dict)]
    assert len(media)==2
    assert set(x['target'] for x in media)=={'/media/source-a','/media/source-b'}
    assert all(x['read_only'] is True for x in media)
    assert all('/media/source' not in str(x) for x in services()['nova-core']['volumes'])

def test_no_remote_edge_or_direct_jellyfin():
    text=(ROOT/'compose.yaml').read_text()
    assert '8096:8096' in text
    assert '0.0.0.0:8096' not in text
    assert 'network_mode: host' not in text
    assert 'NOVA_CONNECT_ENABLED: true' not in text

def test_public_default_status_off(tmp_path):
    from fastapi.testclient import TestClient
    from nova_server.app import make_app
    with TestClient(make_app(tmp_path,directory_options={}),base_url='http://127.0.0.1') as client:
        status=client.get('/api/v1/status').json()
        assert status['remote_access_enabled'] is False
        assert status['directory_enabled'] is False
