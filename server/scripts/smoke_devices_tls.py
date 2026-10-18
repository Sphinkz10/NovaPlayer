"""Real HTTPS pairing/rotation/revocation, isolated temporary certs and databases.

Requires OpenSSL only for disposable test certificates. No verify=False, proxy,
external issuer, credentials or machine trust-store modification.
"""
import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

SERVER = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def ready(client, path, process, expected):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError('Disposable server exited before readiness')
        try:
            if client.get(path).status_code == expected:
                return
        except httpx.HTTPError:
            pass
        time.sleep(.1)
    raise RuntimeError('Disposable server not ready')


def run(output=None):
    openssl = shutil.which('openssl')
    if not openssl and Path(r'C:\Program Files\Git\usr\bin\openssl.exe').is_file():
        openssl = r'C:\Program Files\Git\usr\bin\openssl.exe'
    if not openssl:
        raise RuntimeError('OpenSSL required to generate disposable TLS fixtures')
    with tempfile.TemporaryDirectory(prefix='nova-device-tls-') as temp:
        root = Path(temp)
        state = root/'state'; state.mkdir()
        cert, key = root/'server.crt', root/'server.key'
        subprocess.run([openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=NOVA disposable TLS test', '-addext', 'subjectAltName=IP:127.0.0.1',
                        '-keyout', str(key), '-out', str(cert)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        context = ssl.create_default_context(cafile=str(cert))
        admin_port, client_port = free_port(), free_port()
        while client_port == admin_port:
            client_port = free_port()
        origin = f'https://127.0.0.1:{client_port}'
        env = {**os.environ, 'NOVA_STATE_DIR': str(state), 'NOVA_CLIENT_ORIGIN': origin,
               'NOVA_CLIENT_CERT': str(cert), 'NOVA_CLIENT_KEY': str(key),
               'NOVA_JELLYFIN_URL': 'http://127.0.0.1:1'}
        bootstrap = 'disposable-bootstrap-'+'x'*48
        (state/'bootstrap.token').write_text(bootstrap, encoding='ascii')
        processes = []

        def start(command):
            process = subprocess.Popen([sys.executable, *command], cwd=SERVER, env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(process)
            return process

        try:
            admin_process = start(['-m','uvicorn','nova_server.app:app','--host','127.0.0.1',
                                   '--port',str(admin_port),'--no-proxy-headers','--no-access-log'])
            client_process = start(['-m','nova_server.client_api'])
            with httpx.Client(base_url=f'http://127.0.0.1:{admin_port}', trust_env=False, timeout=5) as admin, \
                    httpx.Client(base_url=origin, verify=context, trust_env=False, timeout=5) as client:
                ready(admin, '/api/v1/health/live', admin_process, 200)
                ready(client, '/api/v1/device/me', client_process, 401)
                credentials = {'username':'owner','password':'disposable-owner-password'}
                assert admin.post('/api/v1/admin/bootstrap', json=credentials,
                                  headers={'X-NOVA-Bootstrap':bootstrap}).status_code == 201
                owner = admin.post('/api/v1/admin/login', json=credentials).json()['access_token']
                admin.headers['Authorization'] = 'Bearer '+owner
                # Unknown certificate and wrong hostname must fail before HTTP authorization.
                for url, verify in ((origin, True), (f'https://localhost:{client_port}', context)):
                    try:
                        with httpx.Client(verify=verify, trust_env=False, timeout=3) as untrusted:
                            untrusted.get(url+'/api/v1/device/me')
                    except httpx.ConnectError as error:
                        assert 'CERTIFICATE_VERIFY_FAILED' in str(error), str(error)
                    else:
                        raise AssertionError('Untrusted identity was accepted')
                grant = client.post('/api/v1/device/authorize', json={'label':'TLS test TV'}).json()
                review = admin.post('/api/v1/admin/devices/inspect', json={'user_code':grant['user_code']}).json()
                assert admin.post('/api/v1/admin/devices/decision', json={
                    'user_code':grant['user_code'], 'request_id':review['request_id'], 'approve':True}).status_code == 200
                issued = client.post('/api/v1/device/token', json={'device_code':grant['device_code']}).json()
                client.headers['Authorization'] = 'Bearer '+issued['access_token']
                me = client.get('/api/v1/device/me').json()
                assert me['server_id'] == grant['server_id'] and me['descriptor']['client_origin'] == origin
                assert client.get('/api/v1/admin/devices').status_code == 404
                assert admin.get('/api/v1/admin/devices', headers=dict(client.headers)).status_code == 401
                assert client.post('/api/v1/device/token', json={'device_code':grant['device_code']}).status_code == 400
                # Restart the HTTPS process and retain identity + authorization.
                stop(client_process)
                client_process = start(['-m','nova_server.client_api'])
                ready(client, '/api/v1/device/me', client_process, 200)
                assert client.get('/api/v1/device/me').json()['server_id'] == grant['server_id']
                rotated = client.post('/api/v1/device/refresh', json={'refresh_token':issued['refresh_token']}).json()
                assert client.get('/api/v1/device/me').status_code == 401
                client.headers['Authorization'] = 'Bearer '+rotated['access_token']
                assert client.get('/api/v1/device/me').status_code == 200
                assert admin.delete('/api/v1/admin/devices/'+issued['device_id']).status_code == 200
                assert client.get('/api/v1/device/me').status_code == 401
                assert client.post('/api/v1/device/refresh', json={'refresh_token':rotated['refresh_token']}).status_code == 401
                # HTTP on the TLS port cannot obtain a response containing credentials.
                try:
                    with httpx.Client(trust_env=False, timeout=3) as plain:
                        result = plain.post(f'http://127.0.0.1:{client_port}/api/v1/device/authorize', json={'label':'TV'})
                        assert result.status_code >= 400
                except httpx.HTTPError:
                    pass
                report = {'result':'passed','transport':'real TLS loopback',
                          'checks':['certificate_chain','hostname_mismatch_rejected','unknown_ca_rejected',
                                    'owner_approval','device_token','role_separation','single_use_grant',
                                    'restart_identity_session','refresh_rotation','owner_revocation','no_http_fallback'],
                          'physical_tv_test':False,'directory_test':False,'media_access':False}
                if output:
                    output.mkdir(parents=True, exist_ok=True)
                    (output/'devices-tls.json').write_text(json.dumps(report,indent=2)+'\n', encoding='utf8')
                print(json.dumps(report))
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    stop(process)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    run(parser.parse_args().output)
