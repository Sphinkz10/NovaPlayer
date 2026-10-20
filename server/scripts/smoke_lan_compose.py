"""Disposable generated LAN stack, actual TLS and Jellyfin; never an existing NAS."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import uuid

import httpx
from lan_install import prepare
from smoke_devices_tls import free_port


def run():
    if os.name!='posix' or not shutil.which('docker'):raise SystemExit('Disposable Linux Docker required')
    ip=socket.gethostbyname(socket.gethostname())
    if not ipaddress.ip_address(ip).is_private or ip.startswith('127.'):raise ValueError('Private runner interface required')
    source=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='nova-lan-compose-') as temp:
        root=Path(temp);bundle=root/'bundle';a=root/'a';b=root/'b';a.mkdir();b.mkdir()
        ports={}
        for role in ('admin','client','directory'):
            port=free_port()
            while port in ports.values():port=free_port()
            ports[role]=port
        password=__import__('secrets').token_urlsafe(24)
        owner={'username':'owner','password':password}
        info=prepare(bundle,ip=ip,state_root='/mnt/pool/nova',media_a='/mnt/pool/a',media_b='/mnt/pool/b',
            uid=os.getuid(),gid=os.getgid(),image='ghcr.io/sphinkz10/nova-core@sha256:'+'a'*64,
            version='25.10.5',username='owner',password=password,ports=ports)
        config=json.loads((bundle/'instalar-no-truenas.yaml').read_text())
        image=os.environ.get('NOVA_TEST_IMAGE') or 'nova-lan-test:'+uuid.uuid4().hex
        if not os.environ.get('NOVA_TEST_IMAGE'):
            subprocess.run(['docker','build','-t',image,str(source)],check=True,stdout=subprocess.DEVNULL)
        for name,service in config['services'].items():
            if name!='jellyfin':service['image']=image
            for mount in service['volumes']:
                path=mount['source']
                if path.startswith('/mnt/pool/nova/'):mount['source']=str(bundle/'copiar-para-nas'/path.removeprefix('/mnt/pool/nova/'))
                elif path in ('/mnt/pool/a','/mnt/pool/b'):mount['source']=str(a if path.endswith('/a') else b)
                else:raise ValueError('Unexpected fixture mount')
        (root/'compose.yaml').write_text(json.dumps(config),encoding='utf8')
        project='nova-lan-'+uuid.uuid4().hex[:10]
        def compose(*args):
            return subprocess.run(['docker','compose','-p',project,*args],cwd=root,check=True,
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        context=ssl.create_default_context(cafile=str(bundle/'NOVA-LAN-CA.crt'));context.minimum_version=ssl.TLSVersion.TLSv1_3
        try:
            compose('config','--quiet');compose('up','-d')
            with httpx.Client(verify=context,trust_env=False,timeout=60) as client:
                for _ in range(120):
                    try:
                        if client.get(info['control']+'/api/v1/health/live').status_code==200 and client.get(info['tv_directory']+'/api/v1/directory/health').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(1)
                else:raise AssertionError('LAN services not ready')
                logged=client.post(info['control']+'/api/v1/admin/login',json=owner);assert logged.status_code==200
                admin={'Authorization':'Bearer '+logged.json()['access_token']}
                for _ in range(180):
                    overview=client.get(info['control']+'/api/v1/admin/overview',headers=admin)
                    if overview.status_code==200 and overview.json()['jellyfin']['state'] in ('ready','setup_required'):break
                    time.sleep(1)
                else:raise AssertionError('Jellyfin did not become ready for LAN setup')
                settings=client.get(info['control']+'/api/v1/admin/lan',headers=admin).json()
                assert settings['fingerprint']==info['tv_fingerprint']
                profile=client.get(info['tv_directory']+'/api/v1/directory/bootstrap').json()
                assert profile['origin']==info['tv_directory'] and 'PRIVATE KEY' not in json.dumps(profile)
                compose('exec','-T','jellyfin','/usr/lib/jellyfin-ffmpeg/ffmpeg','-hide_banner','-loglevel','error',
                        '-f','lavfi','-i','color=c=black:s=64x64:r=10','-t','600','-c:v','libx264','-pix_fmt','yuv420p','/cache/fixture.mp4')
                for name,folder in (('A',a),('B',b)):compose('cp','jellyfin:/cache/fixture.mp4',str(folder/('Film '+name+'.mp4')))
                credentials={'username':'mediaowner','password':__import__('secrets').token_urlsafe(24)}
                setup=client.post(info['control']+'/api/v1/admin/setup/jellyfin',headers=admin,json={**credentials,
                    'server_name':'NOVA LAN fixture','libraries':[{'name':'Filmes A','collection_type':'movies','roots':['source-a']},
                    {'name':'Filmes B','collection_type':'movies','roots':['source-b']}]})
                # Setup errors use fixed public codes; do not dump credentials or upstream logs.
                assert setup.status_code==200, 'LAN setup status '+str(setup.status_code)+' code '+str(setup.json().get('error','unknown'))
                for _ in range(60):
                    checked=client.post(info['control']+'/api/v1/admin/setup/jellyfin/verify',headers=admin,json=credentials)
                    assert checked.status_code==200
                    libraries=checked.json()['libraries']
                    if len(libraries)==2 and all(lib['indexed_items']==1 for lib in libraries):break
                    time.sleep(1)
                else:raise AssertionError('LAN media not indexed')
                assert client.post(info['control']+'/api/v1/admin/directory/identity',headers=admin).status_code==200
                published=client.post(info['control']+'/api/v1/admin/directory/publish',headers=admin,json={**owner,'name':'Casa LAN'})
                assert published.status_code==200
                family_password=__import__('secrets').token_urlsafe(24)
                created=client.post(info['control']+'/api/v1/admin/directory/accounts',headers=admin,json={**owner,
                    'member_username':'alice','member_password':family_password})
                assert created.status_code==201
                assert created.json()['media_authorized'] is False
                family=client.post(info['tv_directory']+'/api/v1/directory/login',json={'username':'alice','password':family_password}).json()
                auth={'Authorization':'Bearer '+family['access_token']}
                entries=client.get(info['tv_directory']+'/api/v1/directory/servers',headers=auth).json()['servers'];assert len(entries)==1
                entry=entries[0]['record']['payload']['entry_id']
                assert client.post(info['tv_directory']+'/api/v1/directory/operator/accounts',headers=auth,json={
                    'username':'intruder','password':family_password,'entry_id':entry}).status_code==403
                proof=client.post(info['tv_directory']+'/api/v1/directory/assertions',headers=auth,json={'entry_id':entry}).json()
                grant=client.post(info['client']+'/api/v1/device/authorize',json={'label':'TV LAN fixture','assertion':proof}).json()
                review=client.post(info['control']+'/api/v1/admin/devices/inspect',headers=admin,json={'user_code':grant['user_code']}).json()
                selected=sorted(libraries,key=lambda lib:lib['name'])[0]['id']
                assert client.post(info['control']+'/api/v1/admin/members',headers=admin,json={**credentials,
                    'subject':family['account_id'],'libraries':[selected]}).status_code==200
                review=client.post(info['control']+'/api/v1/admin/devices/inspect',headers=admin,json={'user_code':grant['user_code']}).json()
                assert client.post(info['control']+'/api/v1/admin/devices/decision',headers=admin,json={
                    'user_code':grant['user_code'],'request_id':review['request_id'],'approve':True}).status_code==200
                tokens=client.post(info['client']+'/api/v1/device/token',json={'device_code':grant['device_code']}).json()
                device={'Authorization':'Bearer '+tokens['access_token']}
                catalog=client.get(info['client']+'/api/v1/media/libraries/'+selected+'/items',headers=device)
                assert catalog.status_code==200 and len(catalog.json()['items'])==1
                item=catalog.json()['items'][0]['id']
                stream=client.get(info['client']+'/api/v1/media/libraries/'+selected+'/items/'+item+'/stream',
                                  headers={**device,'Range':'bytes=0-255'})
                assert stream.status_code==206 and len(stream.content)==256
                for service in ('client','tv_directory'):
                    assert client.get(info[service]+'/api/v1/admin/overview',headers=admin).status_code==404
                assert client.get(info['control']+'/api/v1/admin/overview',headers=device).status_code==401
                compose('restart')
                for _ in range(120):
                    try:
                        if client.get(info['tv_directory']+'/api/v1/directory/bootstrap').json()==profile and client.get(info['client']+'/api/v1/device/me',headers=device).status_code==200:break
                    except (httpx.HTTPError,ValueError):pass
                    time.sleep(1)
                else:raise AssertionError('LAN restart/identity continuity failed')
                report={'result':'passed','profile':'generated private LAN','physical_truenas':False,
                    'checks':['three_https_roles','ca_hostname_tls13','control_login','public_pinned_bootstrap',
                    'jellyfin_setup_two_roots','publication_from_container','owner_only_family_creation','directory_discovery',
                    'restricted_account_pairing','catalog_and_range_video','admin_surface_isolation','restart_identity_continuity'],
                    'image':'exact supplied image' if os.environ.get('NOVA_TEST_IMAGE') else 'locally built fixture image'}
                out=Path(os.environ.get('NOVA_EVIDENCE_DIR','server/test-results/lan'));out.mkdir(parents=True,exist_ok=True)
                (out/'lan-server.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report))
                from smoke_lan_recovery import run as recover_lan
                recovered=recover_lan(root,bundle,image,project,info,client,compose,owner=owner,admin=admin,credentials=credentials,
                    family=family,family_password=family_password,tokens=tokens,selected=selected,profile=profile)
                (out/'lan-recovery.json').write_text(json.dumps(recovered,indent=2),encoding='utf8');print(json.dumps(recovered))
        finally:
            subprocess.run(['docker','compose','-p',project,'down','--volumes','--remove-orphans'],cwd=root,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)


if __name__=='__main__':run()
