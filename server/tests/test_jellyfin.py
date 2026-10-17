import asyncio
import json
import httpx
import pytest
from nova_server.jellyfin import probe_jellyfin

@pytest.mark.parametrize('status,expected',[ (401,'unauthorized'),(403,'unauthorized'),(429,'unavailable'),(502,'unavailable'),(503,'unavailable'),(418,'unexpected') ])
@pytest.mark.asyncio
async def test_statuses(status,expected):
    transport=httpx.MockTransport(lambda r:httpx.Response(status))
    result=await probe_jellyfin('http://jellyfin:8096',transport)
    assert result['state']==expected

@pytest.mark.asyncio
async def test_ready():
    transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'Id':'server-a','Version':'12.2.0','StartupWizardCompleted':True}))
    result=await probe_jellyfin('http://jellyfin:8096/',transport)
    assert result=={'state':'ready','server_id':'server-a','version':'12.2.0'}

@pytest.mark.asyncio
async def test_wizard_pending():
    transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'Id':'srv','StartupWizardCompleted':False}))
    assert (await probe_jellyfin('http://localhost',transport))['state']=='setup_required'

@pytest.mark.asyncio
@pytest.mark.parametrize('bad',[None,[],{},'hello',{'Id':123},{'Id':''}])
async def test_invalid_json_shape(bad):
    transport=httpx.MockTransport(lambda r:httpx.Response(200,json=bad))
    assert (await probe_jellyfin('http://localhost',transport))['state']=='invalid_response'

@pytest.mark.asyncio
async def test_invalid_json_syntax():
    transport=httpx.MockTransport(lambda r:httpx.Response(200,text='not-json'))
    assert (await probe_jellyfin('http://localhost',transport))['state']=='invalid_response'

@pytest.mark.asyncio
async def test_timeout():
    def handler(r): raise httpx.ReadTimeout('simulated')
    assert (await probe_jellyfin('http://jellyfin',httpx.MockTransport(handler)))['state']=='timeout'

@pytest.mark.asyncio
async def test_offline():
    def handler(r): raise httpx.ConnectError('simulated')
    assert (await probe_jellyfin('http://jellyfin',httpx.MockTransport(handler)))['state']=='offline'

@pytest.mark.asyncio
async def test_does_not_follow_redirects():
    transport=httpx.MockTransport(lambda r:httpx.Response(302,headers={'Location':'https://attacker.invalid/'}))
    result=await probe_jellyfin('http://jellyfin',transport)
    assert result['state']=='unexpected'

@pytest.mark.asyncio
async def test_correct_jellyfin_probe_path():
    seen=[]
    def handler(r):seen.append(r.url.path);return httpx.Response(200,json={'Id':'a'})
    await probe_jellyfin('http://jellyfin:8096/',httpx.MockTransport(handler))
    assert seen==['/System/Info/Public']
