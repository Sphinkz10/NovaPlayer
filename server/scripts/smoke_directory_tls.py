"""Real TLS 1.3 Directory journey on loopback with disposable accounts and keys."""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
import httpx

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
from nova_directory.client import DirectoryClient, server_identity
from nova_directory.protocol import Descriptor, verify_record
from nova_directory.store import Registry
from nova_server.storage import Store
from nova_server.security import hash_password
from smoke_devices_tls import free_port, stop, ready


def make_certificate(root):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME,'NOVA Directory disposable')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
        .not_valid_after(now+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([
            x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256()))
    certificate, private = root/'tls.pem', root/'tls.key'
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    private.chmod(0o600)
    return certificate, private


def run(output=None):
    with tempfile.TemporaryDirectory(prefix='nova-directory-tls-') as folder:
        root = Path(folder); certificate, private = make_certificate(root)
        origin = f'https://127.0.0.1:{free_port()}'
        state = root/'directory'; nova = root/'nova'
        registry = Registry(state, origin)
        passwords = {name:secrets.token_urlsafe(32) for name in ('owner','guest','stranger')}
        for name,password in passwords.items(): registry.create_account(name,password)
        local = Store(nova); local.bootstrap('owner',hash_password(secrets.token_urlsafe(32)))
        sid, signing_key = server_identity(nova, create_key=True)
        clients = []; process = None
        def start():
            return subprocess.Popen([sys.executable,'-m','nova_directory','serve','--state',str(state),
                '--origin',origin,'--certificate',str(certificate),'--key',str(private)], cwd=SERVER,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env={**os.environ})
        def login(name):
            client = DirectoryClient(origin, certificate); clients.append(client)
            client.login(name,passwords[name]); return client
        try:
            process = start()
            context = ssl.create_default_context(cafile=str(certificate))
            context.minimum_version = ssl.TLSVersion.TLSv1_3
            with httpx.Client(base_url=origin,verify=context,trust_env=False,timeout=5) as probe:
                ready(probe,'/api/v1/directory/health',process,200)
                for url,trust in ((origin,True),(origin.replace('127.0.0.1','localhost'),context)):
                    try:
                        with httpx.Client(verify=trust,trust_env=False,timeout=3) as invalid:
                            invalid.get(url+'/api/v1/directory/health')
                    except httpx.ConnectError as error:
                        assert 'CERTIFICATE_VERIFY_FAILED' in str(error)
                    else: raise AssertionError('TLS identity accepted incorrectly')
                legacy = ssl.create_default_context(cafile=str(certificate))
                legacy.maximum_version = ssl.TLSVersion.TLSv1_2
                try:
                    with httpx.Client(verify=legacy,trust_env=False,timeout=3) as old:
                        old.get(origin+'/api/v1/directory/health')
                except httpx.ConnectError: pass
                else: raise AssertionError('Directory accepted TLS below 1.3')
                owner, guest, stranger = (login(name) for name in ('owner','guest','stranger'))
                descriptor = Descriptor(server_id=sid,name='Disposable server',
                    client_origin='https://127.0.0.1:8920',certificate_pem=certificate.read_text())
                record = owner.register(descriptor,signing_key)
                verify_record(record,origin,expected_key=record['payload']['public_key'])
                entry = record['payload']['entry_id']
                assert guest.discover()['servers'] == stranger.discover()['servers'] == []
                assert not owner.discover()['media_authorized']
                owner.request('PUT',f'servers/{entry}/members',{'username':'guest','allowed':True})
                assert guest.discover()['servers'][0]['record'] == record
                with httpx.Client(base_url=origin,verify=context,trust_env=False) as attack:
                    attack.headers['Authorization'] = 'Bearer '+guest.token
                    assert attack.delete(f'/api/v1/directory/servers/{entry}').status_code == 404
                    assert attack.post('/api/v1/directory/registrations',json={
                        'challenge_id':record['payload']['challenge_id'],'signature':record['signature']}).status_code == 409
                    for path in ('/api/v1/admin/devices','/api/v1/device/me','/Users','/docs'):
                        assert attack.get(path).status_code == 404
                stop(process); process = start()
                ready(probe,'/api/v1/directory/health',process,200)
                assert guest.discover()['servers'][0]['record'] == record
                sid2, key2 = server_identity(nova)
                assert sid2 == sid and key2.public_key().public_bytes_raw() == signing_key.public_key().public_bytes_raw()
                renewed = owner.register(descriptor,key2)
                assert renewed['payload']['version'] == 2 and renewed['payload']['entry_id'] == entry
                owner.request('PUT',f'servers/{entry}/members',{'username':'guest','allowed':False})
                assert guest.discover()['servers'] == []
                owner.request('PUT',f'servers/{entry}/members',{'username':'guest','allowed':True})
                registry.disable_account('guest')
                try: guest.discover()
                except ValueError: pass
                else: raise AssertionError('Disabled account retained discovery')
                owner.request('DELETE',f'servers/{entry}')
                assert owner.discover()['servers'] == []
                # Inspect only the disposable Directory DB: no NOVA signing key or session plaintext.
                with registry.db() as db:
                    retained = '\n'.join(str(tuple(row)) for table in ('accounts','sessions','entries','members','challenges')
                        for row in db.execute('SELECT * FROM '+table))
                assert 'PRIVATE KEY' not in retained
                assert all(password not in retained for password in passwords.values())
                assert all(client.token not in retained for client in clients if client.token)
                report = {'result':'passed','transport':'real TLS 1.3 loopback',
                    'checks':['unknown_ca_rejected','hostname_mismatch_rejected','tls12_rejected',
                        'argon2_login','server_key_proof','account_isolation','explicit_discovery_share',
                        'unauthorized_mutation_rejected','proof_replay_rejected','restart_persistence',
                        'same_key_renewal','membership_revocation','disabled_account','server_removal',
                        'no_plaintext_credentials_in_directory','separate_api_surface'],
                    'public_deployment':False,'android_directory_integration':False,
                    'media_authorization':False,'physical_nas':False}
                if output:
                    Path(output).mkdir(parents=True,exist_ok=True)
                    (Path(output)/'directory-tls.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
                print(json.dumps(report))
        finally:
            for client in clients: client.close()
            if process and process.poll() is None: stop(process)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output')
    run(parser.parse_args().output)
