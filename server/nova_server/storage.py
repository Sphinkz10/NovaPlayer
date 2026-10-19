"""Single-owner SQLite bootstrap/storage boundary for local P01; no media stored."""
from __future__ import annotations
import sqlite3
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from .security import token_hash

SCHEMA_VERSION = 3

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS admin (
 id INTEGER PRIMARY KEY CHECK (id = 1), username TEXT NOT NULL, password_hash TEXT NOT NULL,
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 digest TEXT PRIMARY KEY, admin_id INTEGER NOT NULL, expires_at INTEGER NOT NULL,
 created_at INTEGER NOT NULL, FOREIGN KEY(admin_id) REFERENCES admin(id)
);
CREATE TABLE IF NOT EXISTS login_attempts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL,
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS connect_drafts (
 provider TEXT PRIMARY KEY CHECK(provider IN ('wireguard','tailscale','netbird')),
 configuration TEXT NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jellyfin_setup (
 id INTEGER PRIMARY KEY CHECK(id=1), server_id TEXT, report TEXT,
 lease TEXT, lease_until INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO jellyfin_setup(id) VALUES(1);
CREATE TABLE IF NOT EXISTS server_identity (
 id INTEGER PRIMARY KEY CHECK(id=1), server_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS device_requests (
 id TEXT PRIMARY KEY, device_digest TEXT NOT NULL UNIQUE, user_digest TEXT NOT NULL UNIQUE,
 label TEXT NOT NULL, expires_at INTEGER NOT NULL, next_poll INTEGER NOT NULL,
 poll_interval INTEGER NOT NULL DEFAULT 5, state TEXT NOT NULL DEFAULT 'pending'
 CHECK(state IN ('pending','approved','denied','consumed'))
);
CREATE TABLE IF NOT EXISTS devices (
 id TEXT PRIMARY KEY, label TEXT NOT NULL, created_at INTEGER NOT NULL,
 expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1))
);
CREATE TABLE IF NOT EXISTS device_access (
 digest TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id), expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS device_refresh (
 digest TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id),
 used INTEGER NOT NULL DEFAULT 0 CHECK(used IN (0,1))
);
CREATE TABLE IF NOT EXISTS device_limits (
 bucket TEXT PRIMARY KEY, starts_at INTEGER NOT NULL, count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS identity_assertions (
 id TEXT PRIMARY KEY, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS member_accounts (
 subject TEXT PRIMARY KEY, username TEXT NOT NULL, jellyfin_user TEXT,
 server_id TEXT, policy TEXT, credential BLOB, disabled INTEGER NOT NULL DEFAULT 1,
 revision INTEGER NOT NULL DEFAULT 0
);
"""

class Store:
    def __init__(self, state_dir: str | Path):
        self.dir = Path(state_dir)
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.dir / 'nova.sqlite3'
        self.lock = threading.RLock()
        with self._db() as conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError('Base de dados de uma versão mais recente; restaurar uma cópia compatível.')
            # Versions 1/2 only add tables; existing owners and media setup survive.
            conn.executescript(SCHEMA)
            for table in ('device_requests','devices'):
                columns={row[1] for row in conn.execute('PRAGMA table_info('+table+')')}
                for name in ('account_id','account_name','directory_entry'):
                    if name not in columns:
                        conn.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' TEXT')
            from uuid import uuid4
            conn.execute('INSERT OR IGNORE INTO server_identity(id,server_id) VALUES(1,?)', (str(uuid4()),))
            conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            conn.commit()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.path, timeout=20)
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            with conn:
                yield conn
        finally:
            conn.close()

    def has_admin(self) -> bool:
        with self._db() as con:
            return bool(con.execute('SELECT 1 FROM admin WHERE id=1').fetchone())

    def setup_state(self):
        with self._db() as con:
            sid, report, expiry = con.execute(
                'SELECT server_id,report,lease_until FROM jellyfin_setup WHERE id=1').fetchone()
            return {'server_id': sid, 'last_observation': json.loads(report) if report else None,
                    'busy': expiry > time.time()}

    def acquire_setup(self, lease):
        with self._db() as con:
            con.execute('BEGIN IMMEDIATE')
            return con.execute('UPDATE jellyfin_setup SET lease=?,lease_until=? '
                               'WHERE id=1 AND lease_until<=?',
                               (lease, int(time.time())+120, int(time.time()))).rowcount == 1

    def pin_setup_server(self, lease, server_id):
        with self._db() as con:
            return con.execute('UPDATE jellyfin_setup SET server_id=? WHERE id=1 AND lease=? '
                               'AND (server_id IS NULL OR server_id=?)',
                               (server_id, lease, server_id)).rowcount == 1

    def finish_setup(self, lease, report=None):
        with self._db() as con:
            if report is not None:
                con.execute('UPDATE jellyfin_setup SET report=? WHERE id=1 AND lease=?',
                            (json.dumps(report), lease))
            con.execute('UPDATE jellyfin_setup SET lease=NULL,lease_until=0 WHERE id=1 AND lease=?',
                        (lease,))

    def bootstrap(self, username: str, hashed: str) -> bool:
        with self.lock, self._db() as con:
            try:
                con.execute('INSERT INTO admin(id,username,password_hash,created_at) VALUES(1,?,?,?)',
                            (username, hashed, int(time.time())))
                con.execute('INSERT INTO audit(event,created_at) VALUES(?,?)', ('owner.bootstrap',int(time.time())))
                con.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_admin(self, username: str):
        with self._db() as con:
            return con.execute('SELECT id,password_hash FROM admin WHERE username=?', (username,)).fetchone()

    def save_session(self, token: str, lifetime: int = 3600):
        now=int(time.time())
        with self.lock, self._db() as con:
            con.execute('DELETE FROM sessions WHERE expires_at<=?',(now,))
            con.execute('INSERT INTO sessions(digest,admin_id,expires_at,created_at) VALUES(?,1,?,?)',
                        (token_hash(token),now+lifetime,now))
            con.commit()

    def session_valid(self, token: str) -> bool:
        now=int(time.time())
        with self._db() as con:
            return con.execute('SELECT 1 FROM sessions WHERE digest=? AND expires_at>?',
                               (token_hash(token),now)).fetchone() is not None

    def revoke_session(self, token: str):
        with self.lock, self._db() as con:
            con.execute('DELETE FROM sessions WHERE digest=?', (token_hash(token),))
            con.commit()

    def reserve_login_attempt(self, source: str, max_attempts: int=5, window: int=900) -> int | None:
        """Atomically count failures AND in-flight verifications, across workers."""
        now = int(time.time())
        with self.lock, self._db() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('DELETE FROM login_attempts WHERE created_at<=?', (now-window,))
            n=con.execute('SELECT COUNT(1) FROM login_attempts WHERE source=? AND created_at>?',
                          (source,now-window)).fetchone()[0]
            if n >= max_attempts:
                return None
            return con.execute('INSERT INTO login_attempts(source,created_at) VALUES(?,?)',
                               (source,now)).lastrowid

    def complete_successful_login(self, attempt: int):
        # Never erase failed or in-flight attempts belonging to other requests.
        with self.lock, self._db() as con:
            con.execute('DELETE FROM login_attempts WHERE id=?',(attempt,))

    def connect_drafts(self) -> dict:
        with self._db() as con:
            return {provider: json.loads(config) for provider, config in
                    con.execute('SELECT provider,configuration FROM connect_drafts')}

    def save_connect_draft(self, draft: dict):
        now = int(time.time())
        with self.lock, self._db() as con:
            con.execute('INSERT INTO connect_drafts(provider,configuration,updated_at) VALUES(?,?,?) '
                        'ON CONFLICT(provider) DO UPDATE SET configuration=excluded.configuration, '
                        'updated_at=excluded.updated_at',
                        (draft['provider'], json.dumps(draft, sort_keys=True), now))
            con.execute('INSERT INTO audit(event,created_at) VALUES(?,?)',
                        ('connect.draft_saved.' + draft['provider'], now))
