"""Per-server authenticated encryption for restricted service credentials."""
import hashlib
import os
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretVault:
    def __init__(self,store):self.store=store

    def key(self,create=False):
        path=self.store.dir/'member-secrets.key'
        with self.store._db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS secret_metadata(id INTEGER PRIMARY KEY CHECK(id=1),digest TEXT NOT NULL)')
            previous=db.execute('SELECT digest FROM secret_metadata WHERE id=1').fetchone()
            if not path.exists():
                if previous or not create:raise ValueError('Restore original credential key')
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as out:
                    out.write(secrets.token_bytes(32));out.flush();os.fsync(out.fileno())
            if path.is_symlink() or path.stat().st_nlink!=1 or path.stat().st_size!=32:
                raise ValueError('Invalid credential key')
            if os.name=='posix' and path.stat().st_mode & 0o077:raise ValueError('Private permissions required')
            raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
            if previous and digest!=previous[0]:raise ValueError('Credential key changed')
            db.execute('INSERT OR IGNORE INTO secret_metadata VALUES(1,?)',(digest,))
        return raw

    def seal(self,value,purpose):
        nonce=secrets.token_bytes(12)
        return nonce+AESGCM(self.key(create=True)).encrypt(nonce,value.encode('ascii'),purpose.encode('ascii'))

    def open(self,sealed,purpose):
        if not isinstance(sealed,bytes) or not 29<=len(sealed)<=4096:raise ValueError('Invalid sealed credential')
        return AESGCM(self.key()).decrypt(sealed[:12],sealed[12:],purpose.encode('ascii')).decode('ascii')
