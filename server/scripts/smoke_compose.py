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
        for name in ('compose.yaml', 'Dockerfile', 'requirements.txt', '.dockerignore'):
            shutil.copy2(source/name, root/name)
        shutil.copytree(source/'nova_server', root/'nova_server', ignore=shutil.ignore_patterns('__pycache__'))
        a, b = Path(folder)/'media-a', Path(folder)/'media-b'
        for directory in (a, b):
            directory.mkdir()
            (directory/'read-only-fixture.txt').write_text('NOVA synthetic fixture', encoding='utf8')
        install(str(a), str(b), root=root)
        bootstrap = (root/'state/nova/bootstrap.token').read_text().strip()
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
            compose('config','--quiet')
            compose('up','--build','-d')
            with httpx.Client(trust_env=False, timeout=5) as client:
                await_services(client)
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
                print(json.dumps({'compose':'passed','read_only_sources':2,'restart_persistence':True,
                                  'nova_jellyfin_setup':True,'indexed_media_sources':2,'duplicate_libraries':0}))
        except Exception:
            # Only this disposable CI project; never dump credentials or the environment.
            compose('ps', '--all', check=False)
            compose('logs', '--no-color', '--tail', '100', check=False)
            raise
        finally:
            compose('down','--remove-orphans', check=False)


if __name__ == '__main__':
    run()
