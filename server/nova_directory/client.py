"""Owner-side lab client; private signing key never leaves the NOVA state folder."""
import json
import os
import re
import sqlite3
import ssl
import time
from contextlib import closing
from pathlib import Path

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .protocol import Descriptor, encode, private_origin, message, validate_payload, verify_record


def server_identity(state, *, create_key=False):
    state = Path(state).resolve(strict=True)
    # Refuse to create a new NOVA database accidentally.
    with closing(sqlite3.connect((state/'nova.sqlite3').as_uri()+'?mode=ro', uri=True)) as db:
        if db.execute('SELECT COUNT(*) FROM admin WHERE id=1').fetchone()[0] != 1:
            raise ValueError('NOVA owner setup required')
        server_id = db.execute('SELECT server_id FROM server_identity WHERE id=1').fetchone()[0]
    path = state/'directory-signing.key'
    if create_key and not path.exists():
        raw = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(raw); output.flush(); os.fsync(output.fileno())
    if path.is_symlink() or path.stat().st_nlink != 1 or path.stat().st_size > 512:
        raise ValueError('Invalid key file')
    if os.name == 'posix' and path.stat().st_mode & 0o077:
        raise ValueError('Signing key requires private permissions')
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Ed25519 key required')
    return server_id, key


class DirectoryClient:
    def __init__(self, origin, certificate):
        self.origin = private_origin(origin)
        context = ssl.create_default_context(cafile=str(certificate))
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        self.http = httpx.Client(base_url=origin, verify=context, trust_env=False,
                                 follow_redirects=False, timeout=5)
        self.token = None
        self.account = None

    def request(self, method, path, payload=None):
        headers = {'Accept':'application/json','Accept-Encoding':'identity'}
        if self.token:
            headers['Authorization'] = 'Bearer '+self.token
        with self.http.stream(method, '/api/v1/directory/'+path, json=payload, headers=headers) as response:
            if response.status_code not in (200, 201):
                raise ValueError('Directory request refused')
            if response.headers.get('content-type','').split(';')[0] != 'application/json':
                raise ValueError('Invalid Directory response')
            data = bytearray(); deadline = time.monotonic()+15
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline or len(data)+len(chunk) > 2*1024*1024:
                    raise ValueError('Directory response too large or slow')
                data.extend(chunk)
            return json.loads(data)

    def login(self, username, password):
        result = self.request('POST','login',{'username':username,'password':password})
        token = result.get('access_token')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,128}', token):
            raise ValueError('Invalid Directory session')
        self.token, self.account = token, result['account_id']

    def register(self, descriptor, key):
        public = encode(key.public_key().public_bytes_raw())
        payload = self.request('POST','challenges',{'public_key':public,'descriptor':descriptor.model_dump()})
        validate_payload(payload, self.origin, expected_key=public)
        if (payload['owner_id'] != self.account or payload['descriptor'] != descriptor.model_dump() or
                payload['proof_expires_at'] <= time.time()):
            raise ValueError('Registration challenge changed')
        signature = encode(key.sign(message(payload)))
        record = self.request('POST','registrations',{'challenge_id':payload['challenge_id'],'signature':signature})
        verify_record(record, self.origin, expected_key=public)
        if record != {'payload':payload,'signature':signature}:
            raise ValueError('Registration response changed')
        return record

    def discover(self):
        result = self.request('GET','servers')
        for entry in result['servers']:
            verify_record(entry['record'], self.origin)
        return result

    def close(self):
        try:
            if self.token:
                self.request('POST','logout')
        except (ValueError, httpx.HTTPError):
            pass  # Session still expires in 15 minutes if the Directory is offline.
        finally:
            self.http.close(); self.token = self.account = None


def main():
    import argparse
    import getpass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('key-init','register','discover','share','unshare','remove'))
    parser.add_argument('--state')
    parser.add_argument('--directory')
    parser.add_argument('--ca')
    parser.add_argument('--username')
    parser.add_argument('--client-origin')
    parser.add_argument('--certificate')
    parser.add_argument('--name')
    parser.add_argument('--entry')
    parser.add_argument('--member')
    args = parser.parse_args()
    if args.action == 'key-init':
        if not args.state:
            parser.error('key-init requires --state')
        _, key = server_identity(args.state, create_key=True)
        print(json.dumps({'public_key':encode(key.public_key().public_bytes_raw())}))
        return
    if not all((args.directory,args.ca,args.username)):
        parser.error('requires --directory, --ca and --username')
    client = DirectoryClient(args.directory, args.ca)
    try:
        client.login(args.username, getpass.getpass('Palavra-passe Directory: '))
        if args.action == 'register':
            if not all((args.state,args.client_origin,args.certificate,args.name)):
                parser.error('register requires --state, --client-origin, --certificate and --name')
            server_id, key = server_identity(args.state)
            descriptor = Descriptor(server_id=server_id, name=args.name, client_origin=args.client_origin,
                                    certificate_pem=Path(args.certificate).read_text(encoding='ascii'))
            record = client.register(descriptor, key)
            print(json.dumps({'entry_id':record['payload']['entry_id'],'expires_at':record['payload']['expires_at']}))
        elif args.action == 'discover':
            print(json.dumps(client.discover(), ensure_ascii=True, indent=2))
        else:
            if not args.entry or (args.action != 'remove' and not args.member):
                parser.error('requires --entry and, for sharing, --member')
            # CLI path components never accept arbitrary URL fragments.
            from .protocol import ID
            if not re.fullmatch(ID, args.entry):
                raise ValueError('Invalid entry')
            if args.action == 'remove':
                result = client.request('DELETE','servers/'+args.entry)
            else:
                result = client.request('PUT','servers/'+args.entry+'/members',
                                        {'username':args.member,'allowed':args.action=='share'})
            print(json.dumps(result))
    finally:
        client.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, httpx.HTTPError, sqlite3.Error, InvalidSignature):
        raise SystemExit('Operação Directory recusada. Verifica identidade, confiança TLS, conta e disponibilidade.') from None
