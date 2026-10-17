"""Single-owner SQLite bootstrap/storage boundary for local P01; no media stored."""
from __future__ import annotations
import sqlite3
import threading
import time
from pathlib import Path
from .security import token_hash

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
"""

class Store:
    def __init__(self, state_dir: str | Path):
        self.dir = Path(state_dir)
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.dir / 'nova.sqlite3'
        self.lock = threading.RLock()
        with self._db() as conn:
            conn.executescript(SCHEMA)
            conn.commit()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=20)
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def has_admin(self) -> bool:
        with self._db() as con:
            return bool(con.execute('SELECT 1 FROM admin WHERE id=1').fetchone())

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

    def login_blocked(self, source: str, max_failures: int=5, window: int=900) -> bool:
        with self._db() as con:
            n=con.execute('SELECT COUNT(1) FROM login_attempts WHERE source=? AND created_at>?',
                          (source,int(time.time())-window)).fetchone()[0]
        return n >= max_failures

    def failed_login(self, source: str):
        now=int(time.time())
        with self.lock, self._db() as con:
            con.execute('DELETE FROM login_attempts WHERE created_at<?',(now-86400,))
            con.execute('INSERT INTO login_attempts(source,created_at) VALUES(?,?)',(source,now))
            con.commit()

    def clear_login_attempts(self, source: str):
        with self.lock, self._db() as con:
            con.execute('DELETE FROM login_attempts WHERE source=?',(source,))
            con.commit()
