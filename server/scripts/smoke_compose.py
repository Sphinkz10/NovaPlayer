"""Linux Docker integration gate. Uses a unique project and disposable bind mounts.

Verifies boot, HTTP, read-only mounts, restart and owner/session persistence.
It does NOT prove media indexing, playback, VPN, or TrueNAS compatibility.
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
        root = Path(folder)
        for name in ('compose.yaml', 'Dockerfile', 'requirements.txt', '.dockerignore'):
            shutil.copy2(source/name, root/name)
        shutil.copytree(source/'nova_server', root/'nova_server', ignore=shutil.ignore_patterns('__pycache__'))
        a, b = root/'media-a', root/'media-b'
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
                compose('restart')
                await_services(client)
                assert client.get(base+'/api/v1/status').json()['owner_setup_required'] is False
                assert client.get(base+'/api/v1/admin/overview', headers=headers).status_code == 200
                assert not (root/'state/nova/bootstrap.token').exists()
                print(json.dumps({'compose':'passed','read_only_sources':2,'restart_persistence':True}))
        except Exception:
            # Only this disposable CI project; never dump credentials or the environment.
            compose('ps', '--all', check=False)
            compose('logs', '--no-color', '--tail', '100', check=False)
            raise
        finally:
            compose('down','--remove-orphans', check=False)


if __name__ == '__main__':
    run()
