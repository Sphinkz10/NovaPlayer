import pytest
from nova_server.storage import Store
from test_api import bootstrap, login

VALID = [
    {'provider':'wireguard', 'gateway_url':'https://10.90.0.1:8920',
     'gateway_mode':'managed', 'endpoint_host':'vpn.example.org', 'endpoint_port':51820},
    {'provider':'tailscale', 'gateway_url':'https://100.100.1.1:8920', 'tailnet':'owner.example'},
    {'provider':'netbird', 'gateway_url':'https://100.90.0.1:8920', 'management_url':'https://api.netbird.io'},
]


def authorized(client):
    bootstrap(client)
    return {'Authorization':'Bearer '+login(client).json()['access_token']}


def test_provider_configuration_requires_owner(test_client):
    client, _ = test_client
    assert client.get('/api/v1/admin/connect').status_code == 401
    assert client.put('/api/v1/admin/connect/draft', json=VALID[0]).status_code == 401


def test_three_drafts_persist_without_activating_any_provider(test_client):
    client, state = test_client
    headers = authorized(client)
    for draft in VALID:
        response = client.put('/api/v1/admin/connect/draft', json=draft, headers=headers)
        assert response.status_code == 200
        assert response.json()['remote_access_enabled'] is False
    data = client.get('/api/v1/admin/connect', headers=headers).json()
    assert data['active_provider'] is None
    assert {p['id'] for p in data['providers']} == {'wireguard','tailscale','netbird'}
    assert not any(p['can_activate'] for p in data['providers'])
    assert Store(state).connect_drafts() == data['drafts']
    assert all(value['schema_version'] == 1 for value in data['drafts'].values())
    assert client.get('/api/v1/status').json()['remote_access_enabled'] is False


@pytest.mark.parametrize('url', ['http://10.0.0.1', 'https://8.8.8.8', 'https://127.0.0.1',
    'https://169.254.0.1', 'https://gateway.example', 'https://user:pass@10.0.0.1',
    'https://10.0.0.1/?secret=hello', 'https://10.0.0.1/#', 'https://10.0.0.1/admin',
    'https://10.0.0.1:0', ' https://10.0.0.1', 'https://10.0.0.1\\admin', 'https://[::1]'])
def test_invalid_gateway_never_saved(test_client, url):
    client, state = test_client
    headers = authorized(client)
    response = client.put('/api/v1/admin/connect/draft', json={**VALID[0], 'gateway_url':url}, headers=headers)
    assert response.status_code == 422
    assert Store(state).connect_drafts() == {}


@pytest.mark.parametrize('change', [{'provider':'unknown'}, {'schema_version':2},
    {'private_key':'do-not-store'}, {'enabled':True}, {'endpoint_port':0},
    {'endpoint_port':'51820'}, {'management_url':'https://wrong-provider.example'}])
def test_reject_secret_fields_unknown_versions_and_cross_provider_options(test_client, change):
    client, _ = test_client
    headers = authorized(client)
    assert client.put('/api/v1/admin/connect/draft', json={**VALID[0], **change}, headers=headers).status_code == 422


def test_netbird_management_requires_https_origin(test_client):
    client, _ = test_client
    headers = authorized(client)
    for url in ['http://api.netbird.io', 'https://user:secret@api.netbird.io', 'https://api.netbird.io?key=secret']:
        assert client.put('/api/v1/admin/connect/draft', json={**VALID[2], 'management_url':url}, headers=headers).status_code == 422
