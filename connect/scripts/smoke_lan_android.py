"""Native TV setup + login + playback over the runner's private IP; no adb reverse."""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import struct

import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'server'),str(ROOT/'server/scripts'),str(ROOT/'server/tests')]
from lan_install import prepare
from jellyfin_m3_fixture import jellyfin_http
from smoke_devices_tls import free_port,ready,stop
from smoke_pairing_android import adb,provision_file,PACKAGE
from nova_server.storage import Store


def run():
    if os.environ.get('GITHUB_ACTIONS')!='true' or adb('shell','getprop','ro.kernel.qemu').strip()!='1':
        raise SystemExit('Only disposable CI emulator permitted')
    # This is a NEW deployment journey. Earlier negative tests deliberately corrupt
    # Directory pins; production must continue to reject that state. Start a fresh
    # disposable app installation rather than adding a trust-reset path to the app.
    assert adb('shell','pm','clear',PACKAGE).strip()=='Success'
    adb('shell','run-as',PACKAGE,'mkdir','-p','files')
    out=ROOT/'connect/test-results/lan';out.mkdir(parents=True,exist_ok=True)
    ip=socket.gethostbyname(socket.gethostname());processes=[]
    with tempfile.TemporaryDirectory(prefix='nova-lan-tv-') as folder,jellyfin_http() as (jf,jf_url):
        bundle=Path(folder)/'bundle';ports={}
        for role in ('admin','client','directory'):
            value=free_port()
            while value in ports.values():value=free_port()
            ports[role]=value
        password=__import__('secrets').token_urlsafe(24)
        info=prepare(bundle,ip=ip,state_root='/mnt/pool/nova',media_a='/mnt/pool/a',media_b='/mnt/pool/b',
            uid=10001,gid=10001,image='ghcr.io/sphinkz10/nova-core@sha256:'+'a'*64,version='25.10.5',username='owner',password=password,ports=ports)
        movie=Path(folder)/'movie.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=320x180:rate=24',
            '-t','15','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart',str(movie)],check=True,timeout=60)
        jf.media_content=movie.read_bytes()
        libraries=[{'id':'a'*32,'name':'Biblioteca A','paths':['/media/source-a']},
                   {'id':'b'*32,'name':'Biblioteca B','paths':['/media/source-b']}]
        for i,library in enumerate(libraries):
            identity=str(i+1)*32;path=library['paths'][0]+'/movie.mp4'
            jf.media_items[library['id']]=[{'Id':identity,'Name':'Filme LAN '+str(i),'Type':'Movie','Path':path,
                'RunTimeTicks':150000000,'MediaSources':[{'Id':identity,'Protocol':'File','Path':path}]}]
        nas=bundle/'copiar-para-nas';store=Store(nas/'nova')
        with store._db() as db:db.execute('UPDATE jellyfin_setup SET server_id=?,report=?',
            (jf.sid,json.dumps({'server_id':jf.sid,'libraries':libraries})))
        context=ssl.create_default_context(cafile=str(bundle/'NOVA-LAN-CA.crt'));context.minimum_version=ssl.TLSVersion.TLSv1_3
        rotation={name:adb('shell','settings','get','system',name).strip()
                  for name in ('accelerometer_rotation','user_rotation')}
        try:
            # Landscape screenshots on the disposable phone emulator; this does
            # not claim Android TV hardware/launcher certification.
            # Rotate the actual display too: API 26 screencap uses physical
            # orientation even when the logical wm size is overridden.
            adb('shell','settings','put','system','accelerometer_rotation','0')
            adb('shell','settings','put','system','user_rotation','1')
            adb('shell','wm','size','720x1280');adb('shell','wm','density','160')
            adb('shell','input','keyevent','KEYCODE_WAKEUP');adb('shell','wm','dismiss-keyguard')
            for role in ('directory','admin','client'):
                identity=nas/'identity'/role
                processes.append(subprocess.Popen([sys.executable,'-m','nova_server.lan_launch',role,'--identity',str(identity),
                    '--config',str(identity/'deployment.json'),'--state',str(nas/('directory' if role=='directory' else 'nova'))],
                    cwd=ROOT/'server',env={**os.environ,'NOVA_JELLYFIN_URL':jf_url},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
            with httpx.Client(verify=context,trust_env=False,timeout=20) as client:
                client.base_url=info['control'];ready(client,'/api/v1/health/live',processes[1],200)
                client.base_url=info['tv_directory'];ready(client,'/api/v1/directory/health',processes[0],200)
                logged=client.post(info['control']+'/api/v1/admin/login',json={'username':'owner','password':password})
                assert logged.status_code==200
                admin={'Authorization':'Bearer '+logged.json()['access_token']}
                assert client.post(info['control']+'/api/v1/admin/directory/identity',headers=admin).status_code==200
                publication=client.post(info['control']+'/api/v1/admin/directory/publish',headers=admin,
                    json={'username':'owner','password':password,'name':'Casa LAN'});assert publication.status_code==200
                family_password=__import__('secrets').token_urlsafe(24)
                created=client.post(info['control']+'/api/v1/admin/directory/accounts',headers=admin,json={
                    'username':'owner','password':password,'member_username':'alice','member_password':family_password})
                assert created.status_code==201
                entry=publication.json()['entry_id'];account=created.json()['account_id']
                provision_file('lan-fixture.json',json.dumps({'origin':info['tv_directory'],'fingerprint':info['tv_fingerprint'],
                                                           'library':libraries[0]['id']}).encode())
                provision_file('mthree-fixture.json',json.dumps({'password':family_password,'account':account,'entry':entry,
                    'library':libraries[0]['id'],'library_name':libraries[0]['name']}).encode())
                adb('shell','am','force-stop',PACKAGE)
                command=['adb','shell','am','instrument','-w','-r','-e','phase','lan-native',
                         PACKAGE+'.test/com.novacinema.connect.DevicePairingInstrumentation']
                process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                timer=threading.Timer(240,process.kill);timer.start();sanitized=[];screenshots=[]
                (out/'screenshots').mkdir(exist_ok=True)
                try:
                    for line in process.stdout:
                        image=re.search(r'INSTRUMENTATION_STATUS: screenshot_name=(tv-(?:libraries|catalogue|detail|player))',line)
                        if image:
                            name=image[1]
                            raw=subprocess.run(['adb','exec-out','screencap','-p'],stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,check=True,timeout=30).stdout
                            assert 1024<len(raw)<=10*1024*1024 and raw[:8]==b'\x89PNG\r\n\x1a\n'
                            width,height=struct.unpack('>II',raw[16:24])
                            (out/'screenshots'/(name+'.png')).write_bytes(raw)
                            assert width>height, f'Expected landscape screenshot, received {width}x{height}'
                            screenshots.append({'name':name+'.png','sha256':hashlib.sha256(raw).hexdigest(),'width':width,'height':height})
                            subprocess.run(['adb','shell','-T','run-as',PACKAGE,'tee','files/lab-screenshot-gate.txt'],
                                input=name.encode('ascii'),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=10)
                            continue
                        match=re.search(r'INSTRUMENTATION_STATUS: pair_code=([A-Z2-9]{4}-[A-Z2-9]{4})',line)
                        if match:
                            code=match[1]
                            review=client.post(info['control']+'/api/v1/admin/devices/inspect',headers=admin,json={'user_code':code}).json()
                            configured=client.post(info['control']+'/api/v1/admin/members',headers=admin,json={
                                'username':'owner','password':'owner-fixture-password','subject':account,'libraries':[libraries[0]['id']]})
                            assert configured.status_code==200
                            review=client.post(info['control']+'/api/v1/admin/devices/inspect',headers=admin,json={'user_code':code}).json()
                            assert client.post(info['control']+'/api/v1/admin/devices/decision',headers=admin,json={
                                'user_code':code,'request_id':review['request_id'],'approve':True}).status_code==200
                        else:sanitized.append(line)
                    process.wait(timeout=5)
                finally:
                    timer.cancel()
                    if process.poll() is None:process.kill();process.wait(timeout=5)
                text=''.join(sanitized);(out/'native-setup.txt').write_text(text,encoding='utf8')
                assert 'INSTRUMENTATION_RESULT: nova_pairing=passed' in text,text
                assert [image['name'] for image in screenshots]==[
                    'tv-libraries.png','tv-catalogue.png','tv-detail.png','tv-player.png']
                report={'result':'passed','api':int(adb('shell','getprop','ro.build.version.sdk').strip()),
                    'adb_reverse':False,'checks':['wrong_fingerprint_denied','http_denied','native_setup_dpad','persisted_authenticated_config',
                    'profile_replacement_denied','directory_login_and_owner_approval','first_video_frame_over_private_ip','tampered_config_fails_closed'],
                    'apk_sha256':hashlib.sha256((ROOT/'connect/app/build/outputs/apk/debug/app-debug.apk').read_bytes()).hexdigest(),
                    'screenshots':screenshots,'screen_data':'synthetic disposable LAN fixture',
                    'display':'landscape phone emulator; not physical Android TV',
                    'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    'production_capture_policy':'FLAG_SECURE unchanged; temporarily cleared/restored only by debug test APK',
                    'jellyfin':'isolated fixture; real Jellyfin covered by generated Docker LAN gate','physical_tv':False}
                (out/'lan-android.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps(report))
        finally:
            adb('shell','am','force-stop',PACKAGE)
            adb('shell','wm','size','reset');adb('shell','wm','density','reset')
            for name,value in rotation.items():
                if value=='null':adb('shell','settings','delete','system',name)
                else:adb('shell','settings','put','system',name,value)
            for name in ('lan-fixture.json','mthree-fixture.json'):
                adb('shell','run-as',PACKAGE,'rm','-f','files/'+name)
            for process in reversed(processes):stop(process)


if __name__=='__main__':run()
