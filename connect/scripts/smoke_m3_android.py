"""Consolidated Directory/account/library journey on disposable CI emulators only."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'server'),str(ROOT/'server/scripts'),str(ROOT/'server/tests')]
from m3_lab import M3Lab
from jellyfin_m3_fixture import jellyfin_http
from nova_directory.protocol import encode,message
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from smoke_pairing_android import adb,provision_file,PACKAGE

OUT=ROOT/'connect/test-results/m3'


def run():
    if os.environ.get('GITHUB_ACTIONS')!='true' or adb('shell','getprop','ro.kernel.qemu').strip()!='1':
        raise SystemExit('Only the disposable GitHub Actions emulator is permitted.')
    OUT.mkdir(parents=True,exist_ok=True);results=[];ports=[]
    with tempfile.TemporaryDirectory(prefix='nova-android-m3-') as folder,jellyfin_http() as (jf,url):
        libraries=[{'id':'a'*32,'name':'Biblioteca A'},{'id':'b'*32,'name':'Biblioteca B'}]
        with M3Lab(folder,url,libraries=libraries,jellyfin_id=jf.sid) as lab:
            try:
                for port in (lab.api_port,lab.api_b_port,lab.directory_port):
                    adb('reverse',f'tcp:{port}',f'tcp:{port}');ports.append(port)
                provision_file('nova-directory.json',json.dumps(lab.profile()).encode())
                def record(entry):
                    with lab.registry.db() as db:
                        return json.loads(db.execute('SELECT record FROM entries WHERE id=?',(entry,)).fetchone()[0])
                old=record(lab.entry)
                fixture={'password':lab.password,'account':lab.accounts['alice'],'entry':lab.entry,
                         'library':libraries[0]['id'],'library_name':libraries[0]['name'],
                         'record':old,'old_record':old,'foreign_record':record(lab.entry_b)}
                wrong=Ed25519PrivateKey.generate();wrong_public=encode(wrong.public_key().public_bytes_raw())
                fixture['wrong_key']=wrong_public
                fixture['wrong_profile']={**lab.profile(),'certificate_pem':lab.cert_b.read_text()}
                def provision():provision_file('mthree-fixture.json',json.dumps(fixture).encode())
                provision()
                def phase(name):
                    adb('shell','am','force-stop',PACKAGE)
                    command=['adb','shell','am','instrument','-w','-r','-e','phase','m3-'+name,
                             PACKAGE+'.test/com.novacinema.connect.DevicePairingInstrumentation']
                    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                    timer=threading.Timer(180,process.kill);timer.start();sanitized=[]
                    try:
                        for line in process.stdout:
                            match=re.search(r'INSTRUMENTATION_STATUS: pair_code=([A-Z2-9]{4}-[A-Z2-9]{4})',line)
                            if match:lab.approve(match.group(1),0)
                            else:sanitized.append(line)
                        process.wait(timeout=5)
                    finally:
                        timer.cancel()
                        if process.poll() is None:process.kill();process.wait(timeout=5)
                    output=''.join(sanitized)
                    (OUT/(str(len(results))+'-'+name+'.txt')).write_text(output,encoding='utf8')
                    assert 'INSTRUMENTATION_RESULT: nova_pairing=passed' in output,output
                    assert 'INSTRUMENTATION_CODE: -1' in output,output
                    results.append({'phase':name,'result':'passed'})
                def device():
                    found=[d for d in lab.admin.get('/api/v1/admin/devices').json()['devices']
                           if d.get('account_id')==lab.accounts['alice'] and not d['revoked']]
                    assert len(found)==1;return found[0]['device_id']
                phase('security');phase('login');first=device()
                with lab.store._db() as db:db.execute('UPDATE device_access SET expires_at=0 WHERE device_id=?',(first,))
                phase('refresh')
                with lab.store._db() as db:
                    assert db.execute('SELECT SUM(used),COUNT(*) FROM device_refresh WHERE device_id=?',(first,)).fetchone()==(1,2)
                lab.rotate_certificate();fixture['record']=record(lab.entry);provision();phase('rotation')
                changed=json.loads(json.dumps(fixture['record']));changed['payload']['public_key']=wrong_public
                changed['payload']['version']+=1
                changed['signature']=encode(wrong.sign(message(changed['payload'])))
                fixture['changed_key_record']=changed;provision();phase('rollback')
                directory=lab.directory_client('bruno')
                try:fixture['foreign_assertion']=directory.request('POST','assertions',{'entry_id':lab.entry_b})
                finally:directory.close()
                provision();phase('foreign')
                assert lab.admin.delete('/api/v1/admin/devices/'+first).status_code==200
                phase('device-revoked');phase('relogin');second=device();assert second!=first
                assert lab.admin.delete('/api/v1/admin/members/'+lab.accounts['alice']).status_code==200
                phase('account-revoked')
                lab.registry.membership(lab.accounts['operator'],lab.entry,'alice',False)
                phase('unshared');phase('pins-tampered')
                apk=ROOT/'connect/app/build/outputs/apk/debug/app-debug.apk'
                report={'result':'passed','api':int(adb('shell','getprop','ro.build.version.sdk').strip()),
                        'phases':results,'apk_sha256':hashlib.sha256(apk.read_bytes()).hexdigest(),
                        'directory_transport':'TLS 1.3 with pinned certificate and issuer',
                        'jellyfin':'isolated HTTP fixture; real Jellyfin tested by Docker job',
                        'physical_tv':False,'playback':False}
                (OUT/'m3.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
                print(json.dumps(report))
            finally:
                adb('shell','am','force-stop',PACKAGE)
                for name in ('mthree-fixture.json','nova-directory.json'):
                    subprocess.run(['adb','shell','run-as',PACKAGE,'rm','-f','files/'+name],check=False,
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
                for port in ports:adb('reverse','--remove',f'tcp:{port}')


if __name__=='__main__':run()
