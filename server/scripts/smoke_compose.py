"""Linux Docker integration gate. Uses a unique project and disposable bind mounts.

Verifies boot, setup through NOVA, two-source indexing, read-only mounts and restart.
It does NOT prove playback, VPN, or TrueNAS compatibility.
"""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from install import install
from acceptance import inspect_container, summarize


def run():
    if os.name != 'posix' or not shutil.which('docker'):
        raise SystemExit('This gate requires Linux and a running Docker Compose installation.')
    for port in (8787, 8096):
        with socket.socket() as check:
            check.bind(('127.0.0.1', port))  # Never interfere with an existing server.
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='nova-compose-') as folder:
        root = Path(folder)/'package'
        root.mkdir()
        for name in ('compose.yaml', 'Dockerfile', 'requirements.txt', 'requirements-directory.txt', '.dockerignore'):
            shutil.copy2(source/name, root/name)
        for name in ('nova_server', 'nova_directory', 'scripts'):
            shutil.copytree(source/name, root/name, ignore=shutil.ignore_patterns('__pycache__'))
        a, b = Path(folder)/'media-a', Path(folder)/'media-b'
        for directory in (a, b):
            directory.mkdir()
            (directory/'read-only-fixture.txt').write_text('NOVA synthetic fixture', encoding='utf8')
        install(str(a), str(b), root=root)
        # TrueNAS Apps starts from empty state, without the host installer token.
        (root/'state/nova/bootstrap.token').unlink()
        project = 'nova-test-' + uuid.uuid4().hex[:12]
        def compose(*args, check=True):
            return subprocess.run(['docker','compose','-p',project,*args], cwd=root, check=check)
        def await_services(client):
            for _ in range(180):
                try:
                    health = client.get('http://127.0.0.1:8787/api/v1/health/live')
                    jf = client.get('http://127.0.0.1:8096/System/Info/Public')
                    if health.status_code == jf.status_code == 200 and jf.json().get('ProductName') == 'Jellyfin Server':
                        return
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(1)
            raise RuntimeError('Compose services did not become available')
        try:
            if os.environ.get('NOVA_TEST_IMAGE'):
                # Package gate: test the exact image that will be pushed, without rebuilding it.
                rendered = json.loads(subprocess.check_output(
                    ['docker','compose','-p',project,'config','--format','json'],cwd=root))
                rendered['services']['nova-core'].pop('build',None)
                rendered['services']['nova-core']['image'] = os.environ['NOVA_TEST_IMAGE']
                (root/'compose.yaml').write_text(json.dumps(rendered),encoding='utf8')
            compose('config','--quiet')
            compose('up','--build','-d')
            with httpx.Client(trust_env=False, timeout=5) as client:
                await_services(client)
                bootstrap = (root/'state/nova/bootstrap.token').read_text().strip()
                for name in ('source-a', 'source-b'):
                    compose('exec','-T','jellyfin','sh','-c',
                            f'test -r /media/{name}/read-only-fixture.txt && ! touch /media/{name}/must-not-write')
                assert not (a/'must-not-write').exists() and not (b/'must-not-write').exists()
                base = 'http://127.0.0.1:8787'
                account = {'username':'owner','password':'compose-test-only-passphrase'}
                assert client.post(base+'/api/v1/admin/bootstrap', json=account,
                                   headers={'X-NOVA-Bootstrap':bootstrap}).status_code == 201
                login = client.post(base+'/api/v1/admin/login', json=account)
                assert login.status_code == 200
                headers = {'Authorization':'Bearer '+login.json()['access_token']}
                overview = client.get(base+'/api/v1/admin/overview', headers=headers).json()
                assert overview['jellyfin']['state'] in ('ready','setup_required'), overview['jellyfin']['state']
                # Generate tiny synthetic media using the image's bundled ffmpeg.
                compose('exec', '-T', 'jellyfin', '/usr/lib/jellyfin-ffmpeg/ffmpeg',
                        '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        'color=c=black:s=64x64:r=10', '-t', '1', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-y', '/cache/nova-fixture.mp4')
                for name, directory in (('A', a), ('B', b)):
                    compose('cp', 'jellyfin:/cache/nova-fixture.mp4', str(directory/f'NOVA Fixture {name}.mp4'))
                credentials = {'username': 'nova-media-admin', 'password': 'compose-jellyfin-test-password'}
                setup = {**credentials, 'server_name': 'NOVA Docker Lab', 'libraries': [
                    {'name': 'NOVA Fixtures', 'collection_type': 'movies', 'roots': ['source-a', 'source-b']}]}
                result = client.post(base+'/api/v1/admin/setup/jellyfin', headers=headers, json=setup, timeout=55)
                assert result.status_code == 200, result.text
                assert result.json()['wizard_completed'] is True
                # A second setup must reuse the library, never append a duplicate.
                repeat = client.post(base+'/api/v1/admin/setup/jellyfin', headers=headers, json=setup, timeout=55)
                assert repeat.status_code == 200, repeat.text
                for _ in range(60):
                    verification = client.post(base+'/api/v1/admin/setup/jellyfin/verify',
                                               headers=headers, json=credentials, timeout=55)
                    assert verification.status_code == 200, verification.text
                    libraries = verification.json()['libraries']
                    if len(libraries) == 1 and libraries[0]['indexed_items'] == 2:
                        break
                    time.sleep(2)
                else:
                    raise AssertionError('Both synthetic films were not indexed')
                # Independently inspect indexed paths, not only the NOVA summary.
                jf_headers = {'Authorization': 'MediaBrowser Client="NOVA CI", Device="CI", DeviceId="ci-audit", Version="1"'}
                jf_login = client.post('http://127.0.0.1:8096/Users/AuthenticateByName',
                                       headers=jf_headers, json={'Username': credentials['username'], 'Pw': credentials['password']})
                assert jf_login.status_code == 200
                jf_token = jf_login.json()['AccessToken']
                jf_headers['Authorization'] += ', Token="'+jf_token+'"'
                try:
                    items = client.get('http://127.0.0.1:8096/Items', headers=jf_headers,
                                       params={'Recursive': 'true', 'IncludeItemTypes': 'Movie', 'Fields': 'Path'}).json()['Items']
                    assert {item['Path'] for item in items} == {
                        '/media/source-a/NOVA Fixture A.mp4', '/media/source-b/NOVA Fixture B.mp4'}
                    assert len(client.get('http://127.0.0.1:8096/Library/VirtualFolders', headers=jf_headers).json()) == 1
                finally:
                    client.post('http://127.0.0.1:8096/Sessions/Logout', headers=jf_headers)
                for file in (root/'state/nova').iterdir():
                    if file.is_file():
                        data = file.read_bytes()
                        assert credentials['password'].encode() not in data and jf_token.encode() not in data
                compose('restart')
                await_services(client)
                assert client.get(base+'/api/v1/status').json()['owner_setup_required'] is False
                assert client.get(base+'/api/v1/admin/overview', headers=headers).status_code == 200
                assert not (root/'state/nova/bootstrap.token').exists()
                persisted = client.get(base+'/api/v1/admin/setup', headers=headers).json()['last_observation']
                assert persisted['libraries'][0]['indexed_items'] == 2
                # A missing bind source must fail, never silently create an empty library.
                compose('stop')
                offline = b.with_name('media-b-offline')
                b.rename(offline)
                try:
                    failed = compose('up', '-d', '--force-recreate', check=False)
                    assert failed.returncode != 0 and not b.exists()
                finally:
                    offline.rename(b)
                compose('up', '-d', '--force-recreate')
                await_services(client)
                result = client.post(base+'/api/v1/admin/setup/jellyfin/verify', headers=headers,
                                     json=credentials, timeout=55)
                assert result.status_code == 200 and result.json()['libraries'][0]['indexed_items'] == 2
                # Seed only disposable device grants through the domain layer. HTTPS is tested separately.
                def core_python(code, payload=None):
                    result = subprocess.run(['docker','compose','-p',project,'exec','-T','nova-core','python','-c',code],
                        cwd=root, input=json.dumps(payload), capture_output=True, text=True)
                    if result.returncode:
                        try:
                            diagnostic=json.loads(result.stdout)
                            if (set(diagnostic)=={'m3_failure','line'} and isinstance(diagnostic['m3_failure'],str) and
                                    diagnostic['m3_failure'].isidentifier() and isinstance(diagnostic['line'],int)):
                                raise RuntimeError('M3 fixture '+diagnostic['m3_failure']+' at line '+str(diagnostic['line']))
                        except (ValueError,TypeError):pass
                        raise RuntimeError('Device recovery fixture/check failed (output withheld to protect tokens)')
                    return json.loads(result.stdout)
                old_devices = core_python("""
import json
from nova_server.storage import Store
from nova_server.devices import Devices
service=Devices(Store('/data'))
def grant():
    value=service.start('Recovery fixture TV')
    review=service.inspect(value['user_code'])
    service.decide(value['user_code'],review['request_id'],True)
    return value
issued=service.poll(grant()['device_code'])
print(json.dumps({'issued':issued,'pending':grant()['device_code'],'server_id':service.identity()}))
""")
                # Encryption and recovery use the same packaged maintenance tools as installation.
                image = subprocess.check_output(['docker','compose','-p',project,'images','-q','nova-core'],
                                                cwd=root, text=True).strip()
                keys = Path(folder)/'keys'; keys.mkdir()
                backups = Path(folder)/'backups'; backups.mkdir()
                recovered = Path(folder)/'recovered'; recovered.mkdir()
                def helper(arguments, mounts, check=True, capture=False):
                    cmd = ['docker', 'run', '--rm', '--network=none', '--read-only',
                           '--cap-drop=ALL', '--security-opt=no-new-privileges',
                           '--user', f'{os.getuid()}:{os.getgid()}']
                    for host, guest, mode in mounts:
                        cmd.extend(['-v', f'{host}:{guest}:{mode}'])
                    return subprocess.run([*cmd, image, *arguments], check=check,
                                          capture_output=capture, text=True)
                helper(['age-keygen','-o','/keys/recovery.key'], [(keys,'/keys','rw')])
                recipient = helper(['age-keygen','-y','/keys/recovery.key'],
                                   [(keys,'/keys','ro')], capture=True).stdout.strip()
                # Keep a live Jellyfin token in the backup to prove it is revoked on restore.
                jf_auth = client.post('http://127.0.0.1:8096/Users/AuthenticateByName',
                    headers={'Authorization':'MediaBrowser Client="Recovery CI", Device="CI", DeviceId="recovery", Version="1"'},
                    json={'Username': credentials['username'], 'Pw': credentials['password']}).json()
                old_jf_auth = {'Authorization':'MediaBrowser Token="'+jf_auth['AccessToken']+'"'}
                compose('stop')
                deployment = subprocess.check_output(['docker','compose','-p',project,'config','--format','json'], cwd=root)
                (root/'deployment.json').write_bytes(deployment)
                helper(['python','scripts/recovery.py','backup','--state','/state','--output','/backups/nova.age',
                        '--recipient',recipient,'--deployment','/deployment.json','--services-stopped'],
                       [(root/'state','/state','rw'),(backups,'/backups','rw'),(root/'deployment.json','/deployment.json','ro')])
                ciphertext = (backups/'nova.age').read_bytes()
                assert b'SQLite format 3' not in ciphertext and account['password'].encode() not in ciphertext
                corrupt = bytearray(ciphertext); corrupt[-1] ^= 1
                (backups/'corrupt.age').write_bytes(corrupt)
                restore_mounts = [(backups,'/backups','ro'),(keys,'/keys','ro'),(recovered,'/restore','rw')]
                rejected = helper(['python','scripts/recovery.py','restore','--input','/backups/corrupt.age',
                    '--output','/restore/rejected','--identity','/keys/recovery.key'],restore_mounts,check=False,capture=True)
                assert rejected.returncode != 0 and not (recovered/'rejected').exists()
                helper(['python','scripts/recovery.py','restore','--input','/backups/nova.age',
                    '--output','/restore/accepted','--identity','/keys/recovery.key'],restore_mounts)
                # Switch disposable test mounts to the recovered state; original remains untouched.
                restored = recovered/'accepted/state'
                override = {'services':{'nova-core':{'volumes':[f'{restored}/nova:/data:rw']},
                    'jellyfin':{'volumes':[f'{restored}/jellyfin/config:/config:rw',f'{restored}/jellyfin/cache:/cache:rw']}}}
                (root/'compose.override.yaml').write_text(json.dumps(override), encoding='utf8')
                compose('up','-d','--force-recreate')
                await_services(client)
                assert client.get(base+'/api/v1/admin/overview',headers=headers).status_code == 401
                assert client.get('http://127.0.0.1:8096/Users/Me',headers=old_jf_auth).status_code in (401,403)
                fresh = client.post(base+'/api/v1/admin/login',json=account)
                assert fresh.status_code == 200
                restored_headers = {'Authorization':'Bearer '+fresh.json()['access_token']}
                verification = client.post(base+'/api/v1/admin/setup/jellyfin/verify',headers=restored_headers,
                                           json=credentials,timeout=55)
                assert verification.status_code == 200, verification.text
                assert verification.json()['libraries'][0]['indexed_items'] == 2
                assert verification.json()['server_id'] == persisted['server_id']
                assert core_python("""
import json,sys
from nova_server.storage import Store
from nova_server.devices import Devices,DeviceError
service=Devices(Store('/data')); old=json.load(sys.stdin)
assert service.identity()==old['server_id']
for fn,secret in ((service.authenticate,old['issued']['access_token']),
                  (service.refresh,old['issued']['refresh_token']),(service.poll,old['pending'])):
    try: fn(secret)
    except DeviceError: pass
    else: raise AssertionError('Restored credential remained valid')
assert service.list()[0]['revoked']==1
print(json.dumps({'revoked':True}))
""", old_devices)['revoked']
                container_ids = {service:subprocess.check_output(
                    ['docker','compose','-p',project,'ps','-q',service],cwd=root,text=True).strip()
                    for service in ('nova-core','jellyfin')}
                for _ in range(60):
                    snapshot = summarize(inspect_container(container_ids['nova-core']),
                                         inspect_container(container_ids['jellyfin']))
                    if snapshot['snapshot_checks_passed']:
                        break
                    time.sleep(2)
                else:
                    raise AssertionError(snapshot['checks'])
                m3=core_python("""
import json,os,sys
os.environ['NOVA_M3_DISPOSABLE_TEST']='1'
from scripts.smoke_m3_server import run
try:
    print(json.dumps(run('/data','http://jellyfin:8096',**json.load(sys.stdin))))
except Exception as error:
    frame=next((frame for frame in reversed(__import__('traceback').extract_tb(error.__traceback__)) if 'smoke_m3_server' in frame.filename),None)
    print(json.dumps({'m3_failure':type(error).__name__,'line':frame.lineno if frame else None}))
    raise SystemExit(1)
""", {'owner':account,'jellyfin_credentials':credentials})
                report = {'compose':'passed','read_only_sources':2,'restart_persistence':True,
                                  'nova_jellyfin_setup':True,'indexed_media_sources':2,'duplicate_libraries':0,
                                  'missing_source_refused':True,'container_recreation':True,
                                  'encrypted_backup_restore':True,'tampered_backup_rejected':True,
                                  'nova_and_jellyfin_sessions_revoked':True,'device_credentials_and_pending_grants_revoked':True,'snapshot':snapshot,
                                  'physical_truenas_test':False}
                report['m3']=m3
                if os.environ.get('NOVA_EVIDENCE_DIR'):
                    evidence = Path(os.environ['NOVA_EVIDENCE_DIR']); evidence.mkdir(parents=True,exist_ok=True)
                    (evidence/'compose-recovery.json').write_text(json.dumps(report,indent=2),encoding='utf8')
                    (evidence/'m3-server.json').write_text(json.dumps(m3,indent=2),encoding='utf8')
                print(json.dumps(report))
        except Exception:
            # Only this disposable CI project; never dump credentials or the environment.
            compose('ps', '--all', check=False)
            compose('logs', '--no-color', '--tail', '100', check=False)
            raise
        finally:
            compose('down','--remove-orphans', check=False)


if __name__ == '__main__':
    run()
