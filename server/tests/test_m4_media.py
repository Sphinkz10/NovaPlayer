import asyncio
import copy
import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from test_m3_members import members, configure, issue
from nova_server.client_api import make_client_app
from nova_server.devices import DeviceError, Devices
from nova_server.media import Media


@pytest.fixture
def catalog(members, monkeypatch):
    configure(members, 0); configure(members, 1)
    old = members.fixture_jf
    items = []
    content = bytes(range(256))*1000
    events = []
    with members.store._db() as db:
        report=members.store.setup_state()['last_observation']
        for i,lib in enumerate(report['libraries']):lib['paths']=['/media/source-'+('a' if i==0 else 'b')]
        db.execute('UPDATE jellyfin_setup SET report=?',(json.dumps(report),))
    for index in range(2):
        path='/media/source-'+('a' if index==0 else 'b')+'/movie.mp4'
        items.append({'Id':str(index+1)*32, 'Name':'Filme '+str(index), 'Type':'Movie',
            'Overview':'Resumo', 'RunTimeTicks':1000000000, 'Path':path,
            'MediaSources':[{'Id':str(index+1)*32,'Protocol':'File','Path':path}],
            'UserData':{'PlaybackPositionTicks':0}})

    def jf(request):
        path = request.url.path
        if path.startswith('/Items') or path.startswith('/Videos/') or path.startswith('/Sessions/Playing'):
            match = re.search(r'Token="([A-Za-z0-9]+)"',request.headers.get('Authorization',''))
            uid = old.tokens.get(match[1]) if match else None
            if uid not in old.users: return httpx.Response(401)
            folders = old.users[uid]['Policy'].get('EnabledFolders',[])
            if path == '/Items':
                library = request.url.params['ParentId']
                selected = [copy.deepcopy(items[i]) for i in range(2)
                            if members.fixture_libs[i]['id']==library and library in folders]
                ids = request.url.params.get('Ids')
                # Deliberately reproduce the real Ids-over-ParentId behavior.
                if ids: selected = [copy.deepcopy(i) for i in items if i['Id']==ids]
                if ids and not selected:return httpx.Response(401)
                search = request.url.params.get('SearchTerm','')
                selected = [i for i in selected if search in i['Name']]
                if request.url.params.get('Filters') == 'IsResumable':
                    assert request.url.params['IsPlayed'] == 'false'
                    assert request.url.params['SortBy'] == 'DatePlayed'
                    selected = [i for i in selected if i['UserData'].get('PlaybackPositionTicks', 0)>0
                                and not i['UserData'].get('Played')]
                return httpx.Response(200,json={'Items':selected,'TotalRecordCount':len(selected)})
            if path.endswith('/Ancestors'):
                target=path.split('/')[2]
                ancestors=[{'Id':members.fixture_libs[i]['id']} for i,value in enumerate(items) if value['Id']==target]
                return httpx.Response(200,json=ancestors)
            if path.endswith('/Images/Primary'):
                assert request.url.params['MaxWidth']=='320' and request.url.params['MaxHeight']=='480'
                return httpx.Response(200, content=b'fixture-jpeg', headers={'Content-Type':'image/jpeg'})
            if path.startswith('/Sessions/Playing'):
                import json
                data=json.loads(request.content); events.append(data)
                next(i for i in items if i['Id']==data['ItemId'])['UserData']['PlaybackPositionTicks']=data['PositionTicks']
                return httpx.Response(204)
            headers = {'Content-Type':'video/mp4','Content-Length':str(len(content)), 'Accept-Ranges':'bytes'}
            value = request.headers.get('Range')
            if value:
                first,last=value[6:].split('-'); first=int(first);last=int(last) if last else len(content)-1
                if first>=len(content): return httpx.Response(416)
                last=min(last,len(content)-1);body=content[first:last+1]
                headers.update({'Content-Length':str(len(body)),'Content-Range':f'bytes {first}-{last}/{len(content)}'})
                return httpx.Response(206,content=body,headers=headers)
            return httpx.Response(200,content=content,headers=headers)
        return old(request)

    members.transport=httpx.MockTransport(jf); members.setup.transport=members.transport
    monkeypatch.setattr('nova_server.members.Members',lambda *a,**k:members)
    monkeypatch.setattr('nova_server.media.Members',lambda *a,**k:members)
    app=make_client_app(members.store.dir,'https://127.0.0.1:8920')
    with TestClient(app,base_url='https://127.0.0.1:8920') as client:
        tokens=[issue(members,i) for i in range(2)]
        yield members,client,tokens,items,content,events


def url(service, index=0, suffix=''):
    return '/api/v1/media/libraries/'+service.fixture_libs[index]['id']+'/items'+suffix


def auth(tokens,index=0):return {'Authorization':'Bearer '+tokens[index]['access_token']}


def test_catalog_search_detail_and_no_upstream_secrets(catalog):
    service,client,tokens,items,_,_=catalog
    result=client.get(url(service),headers=auth(tokens))
    assert result.status_code==200 and [i['id'] for i in result.json()['items']]==[items[0]['Id']]
    assert not any(secret in result.text for secret in ('Path','MediaSources','Token','credential','/media/source-'))
    assert client.get(url(service)+'?search=absent',headers=auth(tokens)).json()['items']==[]
    detail=client.get(url(service,suffix='/'+items[0]['Id']),headers=auth(tokens))
    assert detail.status_code==200 and detail.json()['method']=='DirectPlay'
    assert detail.json()['stream_path'].startswith('/api/v1/media/')


def test_library_and_item_authorization_not_just_item_id(catalog):
    service,client,tokens,items,_,_=catalog
    for index in range(2):
        assert client.get(url(service,index),headers=auth(tokens,1-index)).status_code==404
        for suffix in ('','/stream'):
            assert client.get(url(service,index,'/'+items[1-index]['Id']+suffix),headers=auth(tokens,index)).status_code==404
    assert client.get(url(service)).status_code==401
    for route in ('/api/v1/media/System/Configuration','/Videos/'+items[0]['Id']+'/stream','/Items','/api/v1/admin/members'):
        assert client.get(route,headers=auth(tokens)).status_code==404


def test_ancestor_chain_is_required_even_if_upstream_returns_a_plausible_path(catalog):
    service,client,tokens,items,_,events=catalog
    items[1]['Path']='/media/source-a/forged.mp4'
    endpoint=url(service,suffix='/'+items[1]['Id'])
    assert client.get(endpoint,headers=auth(tokens)).status_code==404
    assert client.get(endpoint+'/stream',headers=auth(tokens)).status_code==404
    assert client.post(endpoint+'/events',headers=auth(tokens),json={'event':'stop','position_ticks':1}).status_code==404
    assert events==[]


@pytest.mark.parametrize('path',['/media/source-a-other/movie.mp4','/media/source-a/../source-b/movie.mp4',
                                 '/media/source-b/movie.mp4','http://server/movie.mp4'])
def test_catalog_does_not_trust_an_incorrect_upstream_parent_filter(catalog,path):
    service,client,tokens,items,_,_=catalog
    items[0]['Path']=path
    assert client.get(url(service),headers=auth(tokens)).status_code==503
    assert client.get(url(service,suffix='/'+items[0]['Id']),headers=auth(tokens)).status_code==404


def test_alternative_media_source_cannot_leave_assigned_library(catalog):
    service,client,tokens,items,_,_=catalog
    items[0]['MediaSources'][0]['Path']='/media/source-b/movie.mp4'
    assert client.get(url(service,suffix='/'+items[0]['Id']+'/stream'),headers=auth(tokens)).status_code==409


def test_stream_range_seek_no_upstream_credentials(catalog):
    service,client,tokens,items,content,_=catalog
    endpoint=url(service,suffix='/'+items[0]['Id']+'/stream')
    result=client.get(endpoint,headers={**auth(tokens),'Range':'bytes=100-199'})
    assert result.status_code==206 and result.content==content[100:200]
    assert result.headers['Content-Range']==f'bytes 100-199/{len(content)}'
    assert result.headers['Cache-Control']=='no-store'
    assert 'Authorization' not in result.headers and 'Location' not in result.headers
    assert client.get(endpoint,headers=auth(tokens)).content==content
    for invalid in ('bytes=0-1,4-8','bytes=-100','bytes=100-1','not-a-range'):
        assert client.get(endpoint,headers={**auth(tokens),'Range':invalid}).status_code==416
    assert client.get(endpoint,headers={**auth(tokens),'Range':'bytes=999999-'}).status_code==416


def test_progress_resume_and_invalid_payloads(catalog):
    service,client,tokens,items,_,events=catalog
    endpoint=url(service,suffix='/'+items[0]['Id'])
    for event in ('start','progress','stop'):
        result=client.post(endpoint+'/events',headers=auth(tokens),json={'event':event,'position_ticks':123000000,'paused':True})
        assert result.status_code==200
    assert len(events)==3 and events[-1]['PlayMethod']=='DirectPlay'
    assert client.get(endpoint,headers=auth(tokens)).json()['item']['position_ticks']==123000000
    for data in ({'event':'stop','position_ticks':True},{'event':'stop','position_ticks':1000000001},
                 {'event':'progress','position_ticks':0,'ItemId':items[1]['Id']}):
        assert client.post(endpoint+'/events',headers=auth(tokens),json=data).status_code==422
    for query in ('?start=-1','?search='+('x'*101),'?kind=admin'):
        assert client.get(url(service)+query,headers=auth(tokens)).status_code==422


def test_revocation_stops_new_catalog_and_active_transfer(catalog):
    service,client,tokens,items,_,_=catalog
    async def transfer():
        response=await Media(service).stream(tokens[0]['access_token'],service.fixture_libs[0]['id'],items[0]['Id'])
        iterator=response.body_iterator
        first=await anext(iterator); assert first
        service.revoke(service.fixture_subjects[0])
        with pytest.raises(DeviceError):await anext(iterator)
        await iterator.aclose()
    asyncio.run(transfer())
    assert client.get(url(service),headers=auth(tokens)).status_code==401


def test_remote_sources_are_not_followed(catalog):
    service,client,tokens,items,_,_=catalog
    items[0]['MediaSources'][0].update(Protocol='Http',Path='http://localhost/admin')
    assert client.get(url(service,suffix='/'+items[0]['Id']+'/stream'),headers=auth(tokens)).status_code==409


@pytest.mark.parametrize('status,headers',[
    (302,{'Location':'http://other-server/secret'}),
    (200,{'Content-Type':'text/html','Content-Length':'8'}),
    (206,{'Content-Type':'video/mp4','Content-Length':'8','Content-Range':'bytes 0-7/8','Content-Encoding':'gzip'}),
    (206,{'Content-Type':'video/mp4','Content-Length':'8','Content-Range':'bytes 2-9/100'}),
    (206,{'Content-Type':'video/mp4','Content-Length':'8','Content-Range':'bytes 0-10/100'}),
])
def test_upstream_redirects_compression_and_bad_range_refused(catalog,status,headers):
    service,client,tokens,items,_,_=catalog
    original=service.transport
    async def hostile(request):
        if request.url.path.startswith('/Videos/'):
            return httpx.Response(status,stream=httpx.ByteStream(b'12345678'),headers=headers)
        return await original.handle_async_request(request)
    service.transport=httpx.MockTransport(hostile)
    result=client.get(url(service,suffix='/'+items[0]['Id']+'/stream'),headers={**auth(tokens),'Range':'bytes=0-7'})
    assert result.status_code==(415 if headers.get('Content-Type')=='text/html' else 502)
    assert 'Location' not in result.headers and 'secret' not in result.text


def test_refresh_does_not_interrupt_open_transfer_but_device_revoke_does(catalog):
    service,client,tokens,items,_,_=catalog
    async def transfer():
        response=await Media(service).stream(tokens[0]['access_token'],service.fixture_libs[0]['id'],items[0]['Id'])
        iterator=response.body_iterator
        assert await anext(iterator)
        Devices(service.store).refresh(tokens[0]['refresh_token'])
        assert await anext(iterator)
        Devices(service.store).revoke(tokens[0]['device_id'])
        with pytest.raises(DeviceError):await anext(iterator)
    asyncio.run(transfer())


def test_policy_change_during_request_discards_result(catalog):
    service,client,tokens,items,_,_=catalog
    original=service.setup._request
    async def revoke(client,method,path,**kwargs):
        result=await original(client,method,path,**kwargs)
        if path=='/Items':service.revoke(service.fixture_subjects[0])
        return result
    service.setup._request=revoke
    assert client.get(url(service),headers=auth(tokens)).status_code==401


def test_continue_watching_respects_account_and_completed_titles(catalog):
    service,client,tokens,items,_,_=catalog
    endpoint=url(service)+'?kind=continue'
    assert client.get(endpoint,headers=auth(tokens)).json()['items']==[]
    items[0]['UserData']['PlaybackPositionTicks']=100000000
    items[1]['UserData']['PlaybackPositionTicks']=200000000
    assert [i['id'] for i in client.get(endpoint,headers=auth(tokens)).json()['items']]==[items[0]['Id']]
    items[0]['UserData']['Played']=True
    assert client.get(endpoint,headers=auth(tokens)).json()['items']==[]


def test_images_authorization_membership_and_no_upstream_headers(catalog):
    service,client,tokens,items,_,_=catalog
    endpoint=url(service,suffix='/'+items[0]['Id']+'/image')
    assert client.get(endpoint).status_code==401
    assert client.get(endpoint,headers=auth(tokens,1)).status_code==404
    assert client.get(url(service,suffix='/'+items[1]['Id']+'/image'),headers=auth(tokens)).status_code==404
    result=client.get(endpoint,headers=auth(tokens))
    assert result.status_code==200 and result.content==b'fixture-jpeg'
    assert result.headers['Cache-Control']=='no-store' and result.headers['Content-Type']=='image/jpeg'
    assert not any(h in result.headers for h in ('Location','Authorization','Set-Cookie'))
    Devices(service.store).revoke(tokens[0]['device_id'])
    assert client.get(endpoint,headers=auth(tokens)).status_code==401


@pytest.mark.parametrize('status,mime,body,extra,expected',[
    (404,'text/plain',b'',{},204),
    (302,'image/jpeg',b'abc',{'Location':'https://external.invalid/secret'},502),
    (200,'image/svg+xml',b'<svg/>',{},502),
    (200,'image/jpeg',b'abc',{'Content-Encoding':'br'},502),
    (200,'image/jpeg',b'x'*1048577,{},502),
    (200,'image/jpeg',b'abc',{'Content-Length':'4'},502),
    (200,'image/jpeg',b'',{},502),
], ids=['missing','redirect','svg','compression','oversize','short-body','empty'])
def test_images_reject_unbounded_active_content_and_redirects(catalog,status,mime,body,extra,expected):
    service,client,tokens,items,_,_=catalog
    original=service.transport
    async def hostile(request):
        if request.url.path.endswith('/Images/Primary'):
            return httpx.Response(status,stream=httpx.ByteStream(body),headers={'Content-Type':mime,**extra})
        return await original.handle_async_request(request)
    service.transport=httpx.MockTransport(hostile)
    result=client.get(url(service,suffix='/'+items[0]['Id']+'/image'),headers=auth(tokens))
    assert result.status_code==expected and 'Location' not in result.headers


def test_image_permission_removed_while_loading_is_discarded(catalog):
    service,client,tokens,items,_,_=catalog
    original=service.transport
    async def revoke(request):
        response=await original.handle_async_request(request)
        if request.url.path.endswith('/Images/Primary'):
            Devices(service.store).revoke(tokens[0]['device_id'])
        return response
    service.transport=httpx.MockTransport(revoke)
    result=client.get(url(service,suffix='/'+items[0]['Id']+'/image'),headers=auth(tokens))
    assert result.status_code==401 and b'fixture-jpeg' not in result.content
