"""Integrated M3 and M4 gateway proof against disposable Docker Jellyfin."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from m3_lab import M3Lab
from nova_server.secret_vault import SecretVault
from nova_server.storage import Store


def run(state,jellyfin_url,owner,jellyfin_credentials):
    if os.environ.get('NOVA_M3_DISPOSABLE_TEST')!='1':
        raise ValueError('This proof is restricted to an explicitly disposable test deployment')
    # Reconfigure only the known synthetic libraries in this disposable CI stack.
    headers={'Authorization':'MediaBrowser Client="NOVA M3 proof", Device="CI", DeviceId="m3-ci", Version="1"'}
    with httpx.Client(base_url=jellyfin_url,trust_env=False,timeout=15) as jf:
        login=jf.post('/Users/AuthenticateByName',headers=headers,
                      json={'Username':jellyfin_credentials['username'],'Pw':jellyfin_credentials['password']})
        assert login.status_code==200
        headers['Authorization']+=', Token="'+login.json()['AccessToken']+'"'
        try:
            libraries=jf.get('/Library/VirtualFolders',headers=headers).json()
            assert all(lib['Name']=='NOVA Fixtures' for lib in libraries)
            for lib in libraries:
                removed=jf.delete('/Library/VirtualFolders',headers=headers,params={'name':lib['Name'],'refreshLibrary':'false'})
                assert removed.status_code in (200,204)
        finally:jf.post('/Sessions/Logout',headers=headers)
    with httpx.Client(base_url='http://127.0.0.1:8787',trust_env=False,timeout=60) as admin:
        logged=admin.post('/api/v1/admin/login',json=owner);assert logged.status_code==200
        admin.headers['Authorization']='Bearer '+logged.json()['access_token']
        try:
            setup=admin.post('/api/v1/admin/setup/jellyfin',json={**jellyfin_credentials,'server_name':'NOVA M3 CI',
                'libraries':[{'name':'Biblioteca A','collection_type':'movies','roots':['source-a']},
                             {'name':'Biblioteca B','collection_type':'movies','roots':['source-b']}]})
            assert setup.status_code==200,setup.text
            for _ in range(60):
                checked=admin.post('/api/v1/admin/setup/jellyfin/verify',json=jellyfin_credentials)
                assert checked.status_code==200
                report=checked.json()
                if len(report['libraries'])==2 and all(lib['indexed_items']==1 for lib in report['libraries']):break
                time.sleep(1)
            else:raise AssertionError('Synthetic libraries were not indexed')
        finally:admin.post('/api/v1/admin/logout')
    libraries=[{'id':lib['id'],'name':lib['name']} for lib in report['libraries']]
    libraries.sort(key=lambda lib:lib['name'])
    with tempfile.TemporaryDirectory(prefix='nova-m3-docker-') as folder:
        with M3Lab(folder,jellyfin_url,state=state,owner=owner,jellyfin_credentials=jellyfin_credentials,
                   libraries=libraries,jellyfin_id=report['server_id']) as lab:
            alice,assertion_a=lab.pair('alice',0);bruno,_=lab.pair('bruno',1)
            media_items=[]
            for index,tokens in enumerate((alice,bruno)):
                auth={'Authorization':'Bearer '+tokens['access_token']}
                result=lab.tv.get('/api/v1/device/libraries',headers=auth)
                assert result.status_code==200,result.text
                assert result.json()['libraries']==[libraries[index]]
                assert 'Token' not in result.text and 'credential' not in result.text
                assert lab.tv.get('/api/v1/device/libraries/'+libraries[1-index]['id']+'/authorization',headers=auth).status_code==404
                assert lab.admin.get('/api/v1/admin/members',headers=auth).status_code==401
                assert lab.tv_b.get('/api/v1/device/me',headers=auth).status_code==401
                with lab.store._db() as db:
                    uid,sealed=db.execute('SELECT jellyfin_user,credential FROM member_accounts WHERE subject=?',
                                         (lab.accounts['alice' if index==0 else 'bruno'],)).fetchone()
                token=SecretVault(lab.store).open(sealed,'member:'+lab.accounts['alice' if index==0 else 'bruno']+':'+report['server_id'])
                restricted={'Authorization':'MediaBrowser Client="NOVA M3 CI", Device="CI", DeviceId="check", Version="1", Token="'+token+'"'}
                with httpx.Client(base_url=jellyfin_url,trust_env=False,timeout=10) as jf:
                    own=jf.get('/Items',headers=restricted,params={'UserId':uid,'ParentId':libraries[index]['id'],
                               'Recursive':'true','IncludeItemTypes':'Movie'})
                    assert own.status_code==200 and len(own.json()['Items'])==1, 'Jellyfin own library access failed'
                    other=jf.get('/Items',headers=restricted,params={'UserId':uid,'ParentId':libraries[1-index]['id'],
                                 'Recursive':'true','IncludeItemTypes':'Movie'})
                    assert other.status_code in (401,403,404) or (other.status_code==200 and not other.json()['Items']), 'Jellyfin cross-library access was not denied'
                    # General configuration is readable by authenticated Jellyfin users.
                    # This resource explicitly requires administrative elevation.
                    system=jf.get('/System/Configuration/MetadataOptions/Default',headers=restricted)
                    assert system.status_code in (401,403), 'Restricted Jellyfin user retained administrative access'
                media='/api/v1/media/libraries/'+libraries[index]['id']+'/items'
                catalog=lab.tv.get(media,headers=auth)
                assert catalog.status_code==200 and len(catalog.json()['items'])==1, 'NOVA media catalog failed'
                item=catalog.json()['items'][0]['id'];media_items.append(item)
                detail=lab.tv.get(media+'/'+item,headers=auth)
                assert detail.status_code==200 and detail.json()['method']=='DirectPlay', 'NOVA detail failed'
                assert not any(value in detail.text for value in ('/media/source-','AccessToken','MediaSources','Path'))
                assert set(detail.json())=={'server_id','account_id','library_id','item','method','stream_path'}
                chunk=lab.tv.get(media+'/'+item+'/stream',headers={**auth,'Range':'bytes=0-255'})
                assert chunk.status_code==206 and len(chunk.content)==256, 'NOVA Range stream failed'
                assert 'ftyp' in chunk.content[:32].decode('latin1'), 'NOVA original MP4 bytes missing'
                total=int(chunk.headers['Content-Range'].split('/')[1])
                tail=lab.tv.get(media+'/'+item+'/stream',headers={**auth,'Range':f'bytes={total-128}-{total-1}'})
                assert tail.status_code==206 and len(tail.content)==128, 'NOVA seek range failed'
                for event in ('start','progress','stop'):
                    result=lab.tv.post(media+'/'+item+'/events',headers=auth,json={
                        'event':event,'position_ticks':0 if event=='start' else 1800000000,'paused':event!='start'})
                    assert result.status_code==200, 'Jellyfin playback event failed'
                resumed=lab.tv.get(media+'/'+item,headers=auth)
                assert resumed.status_code==200 and resumed.json()['item']['position_ticks']==1800000000, 'Jellyfin resume missing'
            for index,tokens in enumerate((alice,bruno)):
                auth={'Authorization':'Bearer '+tokens['access_token']}
                own='/api/v1/media/libraries/'+libraries[index]['id']+'/items/'
                foreign='/api/v1/media/libraries/'+libraries[1-index]['id']+'/items'
                assert lab.tv.get(foreign,headers=auth).status_code==404
                assert lab.tv.get(own+media_items[1-index],headers=auth).status_code==404
                assert lab.tv.post(own+media_items[1-index]+'/events',headers=auth,
                                   json={'event':'stop','position_ticks':1}).status_code==404
                denied=lab.tv.get(own+media_items[1-index]+'/stream',headers=auth)
                if denied.status_code!=404:
                    error=denied.json().get('error','unexpected') if denied.headers.get('Content-Type','').startswith('application/json') else 'non_json'
                    code=error if isinstance(error,str) and error.isidentifier() and len(error)<=60 else 'unexpected'
                    # Only a sanitized status/code enters the diagnostic class name, never response bodies/tokens.
                    raise type('M4ForeignStatus'+str(denied.status_code)+'_'+code,(AssertionError,),{})()
            replay=lab.tv.post('/api/v1/device/authorize',json={'label':'replay','assertion':assertion_a})
            assert replay.status_code==409
            directory=lab.directory_client('bruno')
            try:foreign=directory.request('POST','assertions',{'entry_id':lab.entry_b})
            finally:directory.close()
            assert lab.tv.post('/api/v1/device/authorize',json={'label':'wrong server','assertion':foreign}).status_code==403
            renewed=lab.admin.post('/api/v1/admin/directory/renew')
            assert renewed.status_code==200 and renewed.json()['version']==2
            revoked=lab.admin.delete('/api/v1/admin/devices/'+alice['device_id']);assert revoked.status_code==200
            assert lab.tv.get('/api/v1/device/libraries',headers={'Authorization':'Bearer '+alice['access_token']}).status_code==401
            assert lab.tv.get('/api/v1/media/libraries/'+libraries[0]['id']+'/items/'+media_items[0]+'/stream',
                              headers={'Authorization':'Bearer '+alice['access_token']}).status_code==401
            revoked=lab.admin.delete('/api/v1/admin/members/'+lab.accounts['bruno']);assert revoked.status_code==200
            assert lab.tv.post('/api/v1/device/refresh',json={'refresh_token':bruno['refresh_token']}).status_code==401
            return {'result':'passed','jellyfin':'real Docker','nova_instances':2,'jellyfin_instances':1,
                'checks':['directory_account_binding','owner_device_approval','two_restricted_jellyfin_users',
                          'nova_library_isolation','jellyfin_library_isolation','jellyfin_admin_denied',
                          'device_token_not_admin','cross_server_token_denied','cross_server_assertion_denied',
                          'assertion_replay_denied','scoped_renewal_without_password','device_revocation','account_revocation'],
                'm4_checks':['catalog_two_sources','detail_sanitized','original_mp4_range','seek_range',
                             'jellyfin_progress_and_resume','cross_library_media_denied','revoked_media_denied'],
                'catalog':True,'playback':'original bytes and Jellyfin progress; decode tested separately on Android',
                'physical_nas':False}


if __name__=='__main__':
    data=json.load(sys.stdin)
    print(json.dumps(run(data['state'],data['jellyfin_url'],data['owner'],data['jellyfin_credentials'])))
