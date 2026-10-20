"""Independent account/registry database. Never opens NOVA/Jellyfin state."""
import json
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from nova_server.security import hash_password, verify_password, token_hash
from .protocol import USERNAME, LEASE, encode, verify_record
from .identity import issuer_key, message as identity_message

DUMMY = '$argon2id$v=19$m=65536,t=3,p=2$bsLfU/8cH1R+4e68utTSNQ$8Tk5/U5Y6zx5/ZrURl0G7DtU5y3EXazaQ+3mifoBRLI'
PASSWORD_SLOTS = threading.BoundedSemaphore(2)
SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS accounts(
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 disabled INTEGER NOT NULL DEFAULT 0 CHECK(disabled IN (0,1)));
CREATE TABLE IF NOT EXISTS sessions(
 digest TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS limits(bucket TEXT PRIMARY KEY, starts_at INTEGER NOT NULL, count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS entries(
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES accounts(id), server_id TEXT NOT NULL,
 public_key TEXT NOT NULL, version INTEGER NOT NULL, record TEXT NOT NULL, expires_at INTEGER NOT NULL,
 disabled INTEGER NOT NULL DEFAULT 0 CHECK(disabled IN (0,1)), UNIQUE(owner_id,server_id));
CREATE TABLE IF NOT EXISTS members(
 entry_id TEXT NOT NULL REFERENCES entries(id), account_id TEXT NOT NULL REFERENCES accounts(id),
 PRIMARY KEY(entry_id,account_id));
CREATE TABLE IF NOT EXISTS challenges(
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES accounts(id), payload TEXT NOT NULL,
 expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS identity_metadata(id INTEGER PRIMARY KEY CHECK(id=1), public_key TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS registration_agents(
 digest TEXT PRIMARY KEY,entry_id TEXT NOT NULL REFERENCES entries(id),expires_at INTEGER NOT NULL);
'''


class DirectoryError(Exception):
    def __init__(self, code, status=400, retry_after=None):
        self.code, self.status, self.retry_after = code, status, retry_after


class Registry:
    def __init__(self, state, audience, clock=time.time):
        self.root = Path(state)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.root/'directory.sqlite3'
        self.audience, self.clock = audience, clock
        with self.db() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise RuntimeError('Newer Directory schema')
            db.executescript(SCHEMA)
            if 'agent_digest' not in {row[1] for row in db.execute('PRAGMA table_info(challenges)')}:
                db.execute('ALTER TABLE challenges ADD COLUMN agent_digest TEXT')
            db.execute('PRAGMA user_version=1')
        self.path.chmod(0o600)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT public_key FROM identity_metadata WHERE id=1').fetchone()
            self.identity_key,self.identity_public=issuer_key(self.root,previous[0] if previous else None)
            db.execute('INSERT OR IGNORE INTO identity_metadata VALUES(1,?)',(self.identity_public,))

    def assertion(self, account, entry):
        now=int(self.clock())
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');self._enabled(db,account)
            row=db.execute('SELECT e.record FROM entries e JOIN accounts a ON a.id=e.owner_id '
                'WHERE e.id=? AND e.disabled=0 AND a.disabled=0 AND e.expires_at>? AND '
                '(e.owner_id=? OR EXISTS(SELECT 1 FROM members m WHERE m.entry_id=e.id AND m.account_id=?))',
                (entry,now,account,account)).fetchone()
            if not row:raise DirectoryError('unknown_entry',404)
            record=json.loads(row[0]);verify_record(record,self.audience,now=now)
            row=db.execute('SELECT username FROM accounts WHERE id=? AND disabled=0',(account,)).fetchone()
            if not row:raise DirectoryError('invalid_session',401)
            p={'purpose':'associate-v1','issuer':self.audience,'audience':record['payload']['descriptor']['server_id'],
               'entry_id':entry,'subject':account,'username':row[0],'assertion_id':str(uuid.uuid4()),
               'issued_at':now,'expires_at':now+90}
            return {'payload':p,'signature':encode(self.identity_key.sign(identity_message(p)))}

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    def create_account(self, username, password, *, share_entry=None, owner=None):
        """Operator CLI only. No anonymous signup or remote account enumeration."""
        if not re.fullmatch(USERNAME, username):
            raise ValueError('Username: 3–40 lowercase letters/digits/_.-, starting with a letter')
        with PASSWORD_SLOTS:
            hashed = hash_password(password)
        account = str(uuid.uuid4())
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if share_entry is not None:
                self._enabled(db,owner)
                if not db.execute('SELECT 1 FROM entries WHERE id=? AND owner_id=? AND disabled=0',(share_entry,owner)).fetchone():
                    raise DirectoryError('unknown_entry',404)
                if db.execute('SELECT COUNT(*) FROM members WHERE entry_id=?',(share_entry,)).fetchone()[0]>=50:
                    raise DirectoryError('member_limit',409)
            if db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] >= 100:
                raise DirectoryError('account_limit', 409)
            try:
                db.execute('INSERT INTO accounts(id,username,password_hash) VALUES(?,?,?)', (account, username, hashed))
            except sqlite3.IntegrityError:
                raise DirectoryError('account_exists', 409) from None
            if share_entry is not None:db.execute('INSERT INTO members VALUES(?,?)',(share_entry,account))
        return account

    def disable_account(self, username):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id FROM accounts WHERE username=?', (username,)).fetchone()
            if not row:
                raise DirectoryError('unknown_account', 404)
            db.execute('UPDATE accounts SET disabled=1 WHERE id=?', (row[0],))
            db.execute('DELETE FROM sessions WHERE account_id=?', (row[0],))
            db.execute('DELETE FROM challenges WHERE owner_id=?', (row[0],))

    def limit(self, action, source, maximum=60, total=240, window=60):
        now = int(self.clock()); blocked = False
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM limits WHERE starts_at<=?', (now-900,))
            for bucket, cap in ((action, total), (action+':'+token_hash(source), maximum)):
                row = db.execute('SELECT starts_at,count FROM limits WHERE bucket=?', (bucket,)).fetchone()
                count = 1 if row is None or row[0]+window <= now else row[1]+1
                if count > cap:
                    blocked = True
                    break
                start = now if row is None or row[0]+window <= now else row[0]
                db.execute('INSERT INTO limits VALUES(?,?,?) ON CONFLICT(bucket) DO UPDATE '
                           'SET starts_at=excluded.starts_at,count=excluded.count', (bucket, start, count))
        if blocked:
            raise DirectoryError('rate_limited', 429, window)

    def login(self, username, password, source):
        self.limit('login-source', source, 10, 100, 900)
        self.limit('login-account', username, 10, 100, 900)
        if not PASSWORD_SLOTS.acquire(blocking=False):
            raise DirectoryError('busy', 503, 5)
        try:
            with self.db() as db:
                row = db.execute('SELECT * FROM accounts WHERE username=?', (username,)).fetchone()
            valid = verify_password(row['password_hash'] if row else DUMMY, password)
        finally:
            PASSWORD_SLOTS.release()
        if not valid or not row or row['disabled']:
            raise DirectoryError('invalid_credentials', 401)
        token, expiry = secrets.token_urlsafe(48), int(self.clock())+900
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._enabled(db, row['id'])
            db.execute('DELETE FROM sessions WHERE expires_at<=?', (int(self.clock()),))
            # Bound retained sessions, including successful repeated logins.
            db.execute('DELETE FROM sessions WHERE digest IN (SELECT digest FROM sessions WHERE account_id=? '
                       'ORDER BY expires_at DESC LIMIT -1 OFFSET 7)', (row['id'],))
            db.execute('INSERT INTO sessions VALUES(?,?,?)', (token_hash(token), row['id'], expiry))
        return {'access_token': token, 'expires_in': 900, 'token_type':'Bearer', 'account_id':row['id']}

    @staticmethod
    def _enabled(db, account):
        if not db.execute('SELECT 1 FROM accounts WHERE id=? AND disabled=0', (account,)).fetchone():
            raise DirectoryError('invalid_session', 401)

    def authenticate(self, token):
        with self.db() as db:
            row = db.execute('SELECT a.id FROM sessions s JOIN accounts a ON a.id=s.account_id '
                             'WHERE s.digest=? AND s.expires_at>? AND a.disabled=0',
                             (token_hash(token), int(self.clock()))).fetchone()
        if not row:
            raise DirectoryError('invalid_session', 401)
        return row[0]

    def logout(self, token):
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE digest=?', (token_hash(token),))

    def challenge(self, owner, request):
        now = int(self.clock())
        try:
            request.descriptor.check_certificate(now)
        except ValueError:
            raise DirectoryError('invalid_certificate') from None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._enabled(db, owner)
            db.execute('DELETE FROM challenges WHERE expires_at<=?', (now,))
            count = db.execute('SELECT COUNT(*) FROM challenges').fetchone()[0]
            own = db.execute('SELECT COUNT(*) FROM challenges WHERE owner_id=?', (owner,)).fetchone()[0]
            if count >= 256 or own >= 8:
                raise DirectoryError('challenge_limit', 429, 60)
            old = db.execute('SELECT * FROM entries WHERE owner_id=? AND server_id=?',
                             (owner, request.descriptor.server_id)).fetchone()
            if old and (old['disabled'] or old['public_key'] != request.public_key):
                raise DirectoryError('identity_locked', 409)
            p = {'purpose':'register-v1', 'audience':self.audience, 'owner_id':owner,
                 'entry_id':old['id'] if old else str(uuid.uuid4()), 'challenge_id':str(uuid.uuid4()),
                 'nonce':encode(secrets.token_bytes(32)), 'public_key':request.public_key,
                 'descriptor':request.descriptor.model_dump(), 'version':old['version']+1 if old else 1,
                 'issued_at':now, 'proof_expires_at':now+60, 'expires_at':now+LEASE}
            db.execute('INSERT INTO challenges(id,owner_id,payload,expires_at) VALUES(?,?,?,?)',
                       (p['challenge_id'], owner, json.dumps(p), now+60))
        return p

    def register(self, owner, proof, *, agent=None):
        now = int(self.clock()); error = None; record = None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._enabled(db, owner)
            if agent and not db.execute('SELECT 1 FROM registration_agents r JOIN entries e ON e.id=r.entry_id '
                    'WHERE r.digest=? AND r.expires_at>? AND e.owner_id=? AND e.disabled=0',(agent,now,owner)).fetchone():
                raise DirectoryError('invalid_renewal_credential',401)
            row = db.execute('SELECT payload FROM challenges WHERE id=? AND owner_id=? AND expires_at>? '
                             'AND agent_digest IS ?', (proof.challenge_id,owner,now,agent)).fetchone()
            if not row:
                raise DirectoryError('invalid_challenge', 409)
            # Every submission consumes the challenge, including an invalid signature.
            db.execute('DELETE FROM challenges WHERE id=?', (proof.challenge_id,))
            p = json.loads(row[0]); record = {'payload':p, 'signature':proof.signature}
            try:
                verify_record(record, self.audience, now=now)
            except (ValueError, InvalidSignature):
                error = DirectoryError('invalid_proof', 403)
            if error is None:
                old = db.execute('SELECT * FROM entries WHERE owner_id=? AND server_id=?',
                                 (owner, p['descriptor']['server_id'])).fetchone()
                if old and (old['disabled'] or old['id'] != p['entry_id'] or old['public_key'] != p['public_key'] or
                            old['version']+1 != p['version']):
                    error = DirectoryError('stale_challenge', 409)
                elif not old and (p['version'] != 1 or
                        db.execute('SELECT COUNT(*) FROM entries WHERE owner_id=?', (owner,)).fetchone()[0] >= 20 or
                        db.execute('SELECT COUNT(*) FROM entries').fetchone()[0] >= 200):
                    error = DirectoryError('entry_limit', 409)
                elif old:
                    db.execute('UPDATE entries SET version=?,record=?,expires_at=? WHERE id=?',
                               (p['version'], json.dumps(record), p['expires_at'], p['entry_id']))
                else:
                    db.execute('INSERT INTO entries(id,owner_id,server_id,public_key,version,record,expires_at) VALUES(?,?,?,?,?,?,?)',
                               (p['entry_id'],owner,p['descriptor']['server_id'],p['public_key'],p['version'],
                                json.dumps(record),p['expires_at']))
        if error:
            raise error
        return record

    def renewal_credential(self,owner,entry):
        token=secrets.token_urlsafe(48);expiry=int(self.clock())+30*86400
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');self._enabled(db,owner)
            if not db.execute('SELECT 1 FROM entries WHERE id=? AND owner_id=? AND disabled=0',(entry,owner)).fetchone():
                raise DirectoryError('unknown_entry',404)
            db.execute('DELETE FROM registration_agents WHERE entry_id=?',(entry,))
            db.execute('INSERT INTO registration_agents VALUES(?,?,?)',(token_hash(token),entry,expiry))
        return {'credential':token,'expires_at':expiry,'scope':'registration:renew'}

    def _agent(self,token):
        with self.db() as db:
            row=db.execute('SELECT e.owner_id,e.id,e.server_id,e.public_key FROM registration_agents r '
                'JOIN entries e ON e.id=r.entry_id JOIN accounts a ON a.id=e.owner_id '
                'WHERE r.digest=? AND r.expires_at>? AND e.disabled=0 AND a.disabled=0',
                (token_hash(token),int(self.clock()))).fetchone()
        if not row:raise DirectoryError('invalid_renewal_credential',401)
        return row

    def agent_challenge(self,token,descriptor):
        from .protocol import ChallengeRequest
        owner,entry,server,public=self._agent(token)
        if descriptor.server_id!=server:raise DirectoryError('invalid_renewal_target',403)
        payload=self.challenge(owner,ChallengeRequest(public_key=public,descriptor=descriptor))
        with self.db() as db:
            db.execute('UPDATE challenges SET agent_digest=? WHERE id=?',(token_hash(token),payload['challenge_id']))
        return payload

    def agent_register(self,token,proof):
        owner,_,_,_=self._agent(token)
        return self.register(owner,proof,agent=token_hash(token))

    def discover(self, account):
        now = int(self.clock())
        with self.db() as db:
            self._enabled(db, account)
            rows = db.execute('SELECT e.record,a.username FROM entries e JOIN accounts a ON a.id=e.owner_id '
                              'WHERE e.disabled=0 AND a.disabled=0 AND e.expires_at>? AND '
                              '(e.owner_id=? OR EXISTS(SELECT 1 FROM members m WHERE m.entry_id=e.id AND m.account_id=?)) '
                              'ORDER BY e.id', (now, account, account)).fetchall()
        records = []
        for row in rows:
            record = json.loads(row[0])
            try:
                verify_record(record, self.audience, now=now)
            except (ValueError, InvalidSignature):
                continue  # A now-expired TLS identity must not be advertised.
            records.append({'owner':row[1], 'record':record})
        return records

    def membership(self, owner, entry, username, allowed):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE'); self._enabled(db, owner)
            if not db.execute('SELECT 1 FROM entries WHERE id=? AND owner_id=? AND disabled=0', (entry, owner)).fetchone():
                raise DirectoryError('unknown_entry', 404)
            account = db.execute('SELECT id FROM accounts WHERE username=? AND disabled=0', (username,)).fetchone()
            if not account:
                raise DirectoryError('invalid_member', 400)
            if account[0] == owner:
                raise DirectoryError('owner_membership', 409)
            if allowed:
                exists = db.execute('SELECT 1 FROM members WHERE entry_id=? AND account_id=?', (entry, account[0])).fetchone()
                if not exists and (db.execute('SELECT COUNT(*) FROM members WHERE entry_id=?', (entry,)).fetchone()[0] >= 50 or
                        db.execute('SELECT COUNT(*) FROM members WHERE account_id=?', (account[0],)).fetchone()[0] >= 50):
                    raise DirectoryError('member_limit', 409)
                db.execute('INSERT OR IGNORE INTO members VALUES(?,?)', (entry, account[0]))
            else:
                db.execute('DELETE FROM members WHERE entry_id=? AND account_id=?', (entry, account[0]))

    def remove(self, owner, entry):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE'); self._enabled(db, owner)
            if not db.execute('UPDATE entries SET disabled=1,version=version+1 WHERE id=? AND owner_id=? AND disabled=0',
                              (entry, owner)).rowcount:
                raise DirectoryError('unknown_entry', 404)
            db.execute('DELETE FROM members WHERE entry_id=?', (entry,))
