"""Directory account assertions, separate from server registration signatures."""
import json
import os
import re
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from .protocol import ID, USERNAME, encode, decode, private_origin

DOMAIN = b'NOVA-DIRECTORY-IDENTITY-v1\n'


def message(payload):
    return DOMAIN+json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')


def issuer_key(root, expected=None):
    path=root/'directory-identity.key'
    if not path.exists():
        if expected:
            raise ValueError('Recover the original Directory identity key')
        raw=Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd,'wb') as output:
                output.write(raw);output.flush();os.fsync(output.fileno())
    if path.is_symlink() or path.stat().st_nlink!=1 or path.stat().st_size>512:
        raise ValueError('Invalid Directory identity key')
    if os.name=='posix' and path.stat().st_mode & 0o077:
        raise ValueError('Directory identity requires private permissions')
    key=serialization.load_pem_private_key(path.read_bytes(),password=None)
    if not isinstance(key,Ed25519PrivateKey):raise ValueError('Ed25519 key required')
    public=encode(key.public_key().public_bytes_raw())
    if expected and public!=expected:raise ValueError('Directory identity changed')
    return key,public


def verify_assertion(assertion, public, origin, entry, server, now):
    if not isinstance(assertion,dict) or set(assertion)!={'payload','signature'}:
        raise ValueError('Invalid identity assertion')
    p=assertion['payload']
    fields={'purpose','issuer','audience','entry_id','subject','username','assertion_id','issued_at','expires_at'}
    if not isinstance(p,dict) or set(p)!=fields:raise ValueError('Invalid identity fields')
    if p['purpose']!='associate-v1' or p['issuer']!=private_origin(origin) or p['audience']!=server or p['entry_id']!=entry:
        raise ValueError('Invalid identity audience')
    for name in ('audience','entry_id','subject','assertion_id'):
        if not isinstance(p[name],str) or not re.fullmatch(ID,p[name]):raise ValueError('Invalid identity')
    if not isinstance(p['username'],str) or not re.fullmatch(USERNAME,p['username']):raise ValueError('Invalid account name')
    if (type(p['issued_at']) is not int or type(p['expires_at']) is not int or
            p['expires_at']!=p['issued_at']+90 or p['issued_at']>now+5 or now>=p['expires_at']):
        raise ValueError('Invalid identity lifetime')
    Ed25519PublicKey.from_public_bytes(decode(public,32)).verify(decode(assertion['signature'],64),message(p))
    return p
