import os
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def test_client(tmp_path):
    from nova_server.app import make_app
    state=tmp_path/'nova';state.mkdir()
    (state/'bootstrap.token').write_text('unit-'+'x'*60)
    app=make_app(state_dir=state,jellyfin_url='http://test-jellyfin:8096', allowed_hosts=['testserver'])
    with TestClient(app) as client:
        yield client,state
