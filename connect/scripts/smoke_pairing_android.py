"""End-to-end Android pairing against real NOVA HTTP admin + isolated HTTPS API.

Only the disposable CI emulator is modified. Owner credentials stay on the host.
The test APK reports a public pairing code; the host approves it using Control's API.
"""
import json
import hashlib
import os
import re
import secrets
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'server/scripts'))
from smoke_devices_tls import free_port, ready, stop
from device_invitation import export

PACKAGE = 'com.novacinema.connect.poc'
OUT = ROOT/'connect/test-results/pairing'


def adb(*args, timeout=90):
    return subprocess.check_output(['adb',*args], text=True, stderr=subprocess.STDOUT, timeout=timeout)


def provision_file(name, data):
    assert re.fullmatch(r'[a-z-]+\.(json|der)', name)
    subprocess.run(['adb','shell','-T','run-as',PACKAGE,'tee','files/'+name], input=data,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=20)


def run():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or adb('shell','getprop','ro.kernel.qemu').strip() != '1':
        raise SystemExit('Only the disposable GitHub Actions emulator is permitted.')
    # Older emulator images can start with a stale RTC. Keep certificate/expiry
    # checks strict in the product; synchronise only this disposable test device.
    adb('root'); adb('wait-for-device')
    adb('shell','date','-u',datetime.now(timezone.utc).strftime('%m%d%H%M%Y.%S'))
    assert abs(int(adb('shell','date','+%s').strip())-time.time()) < 5
    OUT.mkdir(parents=True,exist_ok=True)
    for path in ('app/build/outputs/apk/debug/app-debug.apk',
                 'app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk'):
        adb('install','-r','-t',str(ROOT/'connect'/path),timeout=180)
    adb('shell','run-as',PACKAGE,'mkdir','-p','files')
    results=[]
    with tempfile.TemporaryDirectory(prefix='nova-android-pairing-') as folder:
        root=Path(folder);state=root/'state';state.mkdir()
        ports=set()
        while len(ports)<3: ports.add(free_port())
        admin_port,client_port,wrong_port=sorted(ports)
        origin=f'https://127.0.0.1:{client_port}'
        wrong_origin=f'https://127.0.0.1:{wrong_port}'
        cert,key,wrong_cert,wrong_key=(root/name for name in ('server.pem','server.key','wrong.pem','wrong.key'))
        for public,private,san in ((cert,key,'127.0.0.1'),(wrong_cert,wrong_key,'10.42.1.2')):
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=NOVA disposable',
                            '-addext','subjectAltName=IP:'+san,'-keyout',str(private),'-out',str(public)],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        bootstrap=secrets.token_urlsafe(48)
        (state/'bootstrap.token').write_text(bootstrap,encoding='ascii')
        env={**os.environ,'NOVA_STATE_DIR':str(state),'NOVA_JELLYFIN_URL':'http://127.0.0.1:1',
             'NOVA_CLIENT_ORIGIN':origin,'NOVA_CLIENT_CERT':str(cert),'NOVA_CLIENT_KEY':str(key)}
        processes=[]
        def launch(command,environment):
            process=subprocess.Popen([sys.executable,*command],cwd=ROOT/'server',env=environment,
                                      stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            processes.append(process);return process
        def database(query,values=()):
            with sqlite3.connect(state/'nova.sqlite3') as db:
                return db.execute(query,values).fetchall()
        try:
            admin_process=launch(['-m','uvicorn','nova_server.app:app','--host','127.0.0.1','--port',str(admin_port),
                                  '--no-proxy-headers','--no-access-log'],env)
            client_process=launch(['-m','nova_server.client_api'],env)
            launch(['-m','nova_server.client_api'],{**env,'NOVA_CLIENT_ORIGIN':wrong_origin,
                                                 'NOVA_CLIENT_CERT':str(wrong_cert),'NOVA_CLIENT_KEY':str(wrong_key)})
            context=ssl.create_default_context(cafile=str(cert))
            with httpx.Client(base_url=f'http://127.0.0.1:{admin_port}',trust_env=False,timeout=5) as admin, \
                    httpx.Client(base_url=origin,verify=context,trust_env=False,timeout=5) as client:
                ready(admin,'/api/v1/health/live',admin_process,200)
                ready(client,'/api/v1/device/me',client_process,401)
                account={'username':'owner','password':secrets.token_urlsafe(32)}
                assert admin.post('/api/v1/admin/bootstrap',json=account,headers={'X-NOVA-Bootstrap':bootstrap}).status_code==201
                admin.headers['Authorization']='Bearer '+admin.post('/api/v1/admin/login',json=account).json()['access_token']
                for port in (client_port,wrong_port): adb('reverse',f'tcp:{port}',f'tcp:{port}')
                invitation=root/'invitation.json';export(state,origin,cert,invitation)
                wrong=root/'wrong-invitation.json';export(state,wrong_origin,wrong_cert,wrong)
                provision_file('pairing-invitation.json',invitation.read_bytes())
                provision_file('wrong-host-invitation.json',wrong.read_bytes())
                provision_file('untrusted-certificate.der',ssl.PEM_cert_to_DER_cert(wrong_cert.read_text()))
                def phase(name):
                    adb('shell','am','force-stop',PACKAGE)
                    # API 26 may reject clearing a log buffer after adbd restarts.
                    # Diagnostics must not prevent the actual security test.
                    subprocess.run(['adb','logcat','-b','crash','-c'],stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL,timeout=20,check=False)
                    command=['adb','shell','am','instrument','-w','-r','-e','phase',name,
                             PACKAGE+'.test/com.novacinema.connect.DevicePairingInstrumentation']
                    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                    timer=threading.Timer(180,process.kill);timer.start()
                    sanitized=[]
                    try:
                        for line in process.stdout:
                            match=re.search(r'INSTRUMENTATION_STATUS: pair_code=([A-Z2-9]{4}-[A-Z2-9]{4})',line)
                            if match:
                                code=match.group(1)
                                reviewed=admin.post('/api/v1/admin/devices/inspect',json={'user_code':code})
                                assert reviewed.status_code==200
                                approved=admin.post('/api/v1/admin/devices/decision',json={'user_code':code,
                                    'request_id':reviewed.json()['request_id'],'approve':True})
                                assert approved.status_code==200
                            else:
                                sanitized.append(line)
                        process.wait(timeout=5)
                    finally:
                        timer.cancel()
                        if process.poll() is None: process.kill();process.wait(timeout=5)
                    output=''.join(sanitized)
                    (OUT/(str(len(results))+'-'+name+'.txt')).write_text(output,encoding='utf8')
                    if 'INSTRUMENTATION_RESULT: nova_pairing=passed' not in output:
                        # Preserve class/line diagnostics, never exception messages or app data.
                        crash=subprocess.run(['adb','logcat','-d','-b','crash','-v','brief'],
                            capture_output=True,text=True,timeout=20,check=False).stdout
                        frames=re.findall(r'\bat ([A-Za-z0-9_.$]+\([A-Za-z0-9_. :]+\))',crash)
                        types=re.findall(r'\b([A-Za-z0-9_.$]+(?:Exception|Error)):',crash)
                        (OUT/(str(len(results))+'-crash.json')).write_text(
                            json.dumps({'types':types,'frames':frames},indent=2)+'\n',encoding='utf8')
                        print(json.dumps({'phase':name,'types':types,'frames':frames}))
                    assert 'INSTRUMENTATION_RESULT: nova_pairing=passed' in output, output
                    assert 'INSTRUMENTATION_CODE: -1' in output, output
                    results.append({'phase':name,'result':'passed'})
                def new_pair():
                    before={d['device_id'] for d in admin.get('/api/v1/admin/devices').json()['devices']}
                    phase('pair')
                    created=[d for d in admin.get('/api/v1/admin/devices').json()['devices'] if d['device_id'] not in before]
                    assert len(created)==1 and not created[0]['revoked']
                    return created[0]['device_id']
                def revoke(device):
                    assert admin.delete('/api/v1/admin/devices/'+device).status_code==200
                phase('security')
                device=new_pair()
                database('UPDATE device_access SET expires_at=0 WHERE device_id=?',(device,))
                phase('refresh')
                assert database('SELECT SUM(used),COUNT(*) FROM device_refresh WHERE device_id=?',(device,))==[(1,2)]
                revoke(device);phase('revoked')
                device=new_pair();phase('rotation-marker');phase('after-marker')
                assert database('SELECT SUM(used),COUNT(*) FROM device_refresh WHERE device_id=?',(device,))==[(0,1)]
                revoke(device)
                device=new_pair();phase('tamper');revoke(device)
                device=new_pair();phase('logout')
                assert database('SELECT revoked FROM devices WHERE id=?',(device,))==[(1,)]
                report={'result':'passed','android_api':adb('shell','getprop','ro.build.version.sdk').strip(),
                        'apk_sha256':hashlib.sha256((ROOT/'connect/app/build/outputs/apk/debug/app-debug.apk').read_bytes()).hexdigest(),
                        'phases':results,'real_tls':True,'owner_approval_api':True,'keystore_persistence':True,
                        'process_restart':True,'refresh_rotation':True,'interrupted_refresh_not_replayed':True,
                        'tampered_storage_rejected':True,'physical_tv':False,'directory':False,'media':False,'vpn_tunnel':False}
                (OUT/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
                print(json.dumps(report))
        finally:
            for port in (client_port,wrong_port):
                subprocess.run(['adb','reverse','--remove',f'tcp:{port}'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for process in reversed(processes):
                if process.poll() is None: stop(process)


if __name__=='__main__': run()
