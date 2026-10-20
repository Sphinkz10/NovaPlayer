"""Owner-approved device grants. Media requires a separate live member/library check.

Opaque credentials are hashed at rest. All grant transitions use a SQLite write
transaction, including polling/replay failures whose side effects must commit.
"""
import secrets
import sqlite3
import time
import uuid

from .security import token_hash

GRANT_TTL = 600
ACCESS_TTL = 300
DEVICE_TTL = 30 * 86400
MAX_DEVICES = 50
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


class DeviceError(Exception):
    def __init__(self, code, status=400, retry_after=None):
        self.code, self.status, self.retry_after = code, status, retry_after


class Devices:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    def identity(self):
        with self.store._db() as db:
            return db.execute('SELECT server_id FROM server_identity WHERE id=1').fetchone()[0]

    def _prune(self, db, now):
        db.execute('DELETE FROM device_requests WHERE expires_at<=?', (now,))
        db.execute('DELETE FROM device_access WHERE expires_at<=?', (now,))
        db.execute('DELETE FROM device_refresh WHERE device_id IN '
                   '(SELECT id FROM devices WHERE expires_at<=?)', (now,))
        db.execute('DELETE FROM device_access WHERE device_id IN '
                   '(SELECT id FROM devices WHERE expires_at<=?)', (now,))
        db.execute('DELETE FROM devices WHERE expires_at<=?', (now,))
        db.execute('DELETE FROM device_limits WHERE starts_at<=?', (now-600,))
        db.execute('DELETE FROM identity_assertions WHERE expires_at<=?',(now,))

    def limit(self, action, source, per_source, total, window=600):
        """Global budget bounds source cardinality too; proxy headers are not trusted."""
        now = int(self.clock())
        blocked = False
        with self.store._db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._prune(db, now)
            for bucket, maximum in ((action, total), (action+':'+token_hash(source), per_source)):
                row = db.execute('SELECT starts_at,count FROM device_limits WHERE bucket=?', (bucket,)).fetchone()
                if row and row[0]+window > now and row[1] >= maximum:
                    blocked = True
                    break
                db.execute('INSERT INTO device_limits VALUES(?,?,1) ON CONFLICT(bucket) '
                           'DO UPDATE SET starts_at=excluded.starts_at, count=?',
                           (bucket, now if not row or row[0]+window <= now else row[0],
                            1 if not row or row[0]+window <= now else row[1]+1))
        if blocked:
            raise DeviceError('slow_down', 429, window)

    def start(self, label, identity=None):
        now = int(self.clock())
        device_code = secrets.token_urlsafe(48)
        code = ''.join(secrets.choice(ALPHABET) for _ in range(8))
        with self.store._db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._prune(db, now)
            if not db.execute('SELECT 1 FROM admin WHERE id=1').fetchone():
                raise DeviceError('owner_setup_required', 409)
            if db.execute('SELECT COUNT(*) FROM device_requests').fetchone()[0] >= 64:
                raise DeviceError('too_many_pending_devices', 429, GRANT_TTL)
            if identity:
                if identity['audience']!=self.identity() or identity['expires_at']<=now:
                    raise DeviceError('invalid_directory_identity',403)
                try:
                    db.execute('INSERT INTO identity_assertions VALUES(?,?)',
                               (identity['assertion_id'],identity['expires_at']))
                except sqlite3.IntegrityError:
                    raise DeviceError('directory_identity_reused',409) from None
            db.execute('INSERT INTO device_requests(id,device_digest,user_digest,label,expires_at,next_poll) '
                       'VALUES(?,?,?,?,?,?)', (str(uuid.uuid4()), token_hash(device_code), token_hash(code),
                                               label, now+GRANT_TTL, now))
            if identity:
                db.execute('UPDATE device_requests SET account_id=?,account_name=?,directory_entry=? WHERE device_digest=?',
                    (identity['subject'],identity['username'],identity['entry_id'],token_hash(device_code)))
        return {'device_code': device_code, 'user_code': code[:4]+'-'+code[4:],
                'expires_in': GRANT_TTL, 'interval': 5, 'server_id': self.identity(),
                'scope': 'device:read'}

    @staticmethod
    def _code_digest(code):
        return token_hash(code.upper().replace('-', '').replace(' ', ''))

    def inspect(self, code):
        with self.store._db() as db:
            row = db.execute('SELECT id,label,expires_at,account_id,account_name FROM device_requests '
                             "WHERE user_digest=? AND state='pending' AND expires_at>?",
                             (self._code_digest(code), int(self.clock()))).fetchone()
        if not row:
            raise DeviceError('invalid_user_code', 404)
        with self.store._db() as db:
            member_ready=bool(row[3] and db.execute('SELECT 1 FROM member_accounts WHERE subject=? AND disabled=0',(row[3],)).fetchone())
        return {'request_id': row[0], 'label': row[1], 'expires_at': row[2],
                'account_id':row[3],'account_name':row[4],
                'member_configured':member_ready,
                'server_id': self.identity(), 'scope': 'device:read'}

    def decide(self, code, request_id, approve):
        now = int(self.clock())
        with self.store._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if approve:
                row=db.execute('SELECT account_id FROM device_requests WHERE id=?',(request_id,)).fetchone()
                if row and row[0] and not db.execute('SELECT 1 FROM member_accounts WHERE subject=? AND disabled=0', (row[0],)).fetchone():
                    raise DeviceError('member_permissions_required',409)
            changed = db.execute("UPDATE device_requests SET state=? WHERE id=? AND user_digest=? "
                                 "AND state='pending' AND expires_at>?",
                                 ('approved' if approve else 'denied', request_id, self._code_digest(code), now)).rowcount
            if not changed:
                raise DeviceError('invalid_user_code', 409)
            db.execute('INSERT INTO audit(event,created_at) VALUES(?,?)',
                       ('device.approved' if approve else 'device.denied', now))
        return {'approved': approve}

    def _issue(self, db, device_id, now, expires_at):
        access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        # One active access token per device, invalidated on refresh.
        db.execute('DELETE FROM device_access WHERE device_id=?', (device_id,))
        db.execute('INSERT INTO device_access VALUES(?,?,?)',
                   (token_hash(access), device_id, min(now+ACCESS_TTL, expires_at)))
        db.execute('INSERT INTO device_refresh(digest,device_id) VALUES(?,?)', (token_hash(refresh), device_id))
        return {'access_token': access, 'refresh_token': refresh, 'token_type': 'Bearer',
                'expires_in': min(ACCESS_TTL, expires_at-now), 'refresh_expires_in': expires_at-now,
                'scope': 'device:read', 'device_id': device_id}

    def poll(self, device_code):
        now, error, result = int(self.clock()), None, None
        with self.store._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id,label,expires_at,next_poll,poll_interval,state,account_id '
                             'FROM device_requests WHERE device_digest=?', (token_hash(device_code),)).fetchone()
            if not row or row[5] == 'consumed':
                error = DeviceError('invalid_grant')
            elif row[2] <= now:
                error = DeviceError('expired_token')
            elif row[5] == 'denied':
                error = DeviceError('access_denied')
            elif row[3] > now:
                interval = min(row[4]+5, 60)
                db.execute('UPDATE device_requests SET next_poll=?,poll_interval=? WHERE id=?',
                           (now+interval, interval, row[0]))
                error = DeviceError('slow_down', 429, interval)
            elif row[5] == 'pending':
                db.execute('UPDATE device_requests SET next_poll=? WHERE id=?', (now+row[4], row[0]))
                error = DeviceError('authorization_pending', 400, row[4])
            else:
                self._prune(db, now)
                if row[6] and not db.execute('SELECT 1 FROM member_accounts WHERE subject=? AND disabled=0',(row[6],)).fetchone():
                    db.execute("UPDATE device_requests SET state='consumed' WHERE id=?",(row[0],))
                    error=DeviceError('access_denied',403)
                elif db.execute('SELECT COUNT(*) FROM devices').fetchone()[0] >= MAX_DEVICES:
                    error = DeviceError('device_limit_reached', 409)
                else:
                    db.execute('INSERT INTO devices(id,label,created_at,expires_at) VALUES(?,?,?,?)',
                               (row[0], row[1], now, now+DEVICE_TTL))
                    db.execute('UPDATE devices SET (account_id,account_name,directory_entry)='
                        '(SELECT account_id,account_name,directory_entry FROM device_requests WHERE id=?) WHERE id=?', (row[0],row[0]))
                    db.execute("UPDATE device_requests SET state='consumed' WHERE id=?", (row[0],))
                    result = self._issue(db, row[0], now, now+DEVICE_TTL)
        if error:
            raise error
        return result

    def refresh(self, token):
        now, error, result = int(self.clock()), None, None
        with self.store._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT d.id,d.expires_at,d.revoked,r.used,d.account_id FROM device_refresh r '
                             'JOIN devices d ON r.device_id=d.id WHERE r.digest=?', (token_hash(token),)).fetchone()
            if not row or row[1] <= now or row[2]:
                error = DeviceError('invalid_grant', 401)
            elif row[4] and not db.execute('SELECT 1 FROM member_accounts WHERE subject=? AND disabled=0',(row[4],)).fetchone():
                self._revoke(db,row[0],now,'device.member_revoked')
                error=DeviceError('invalid_grant',401)
            elif row[3]:
                # Commit revocation BEFORE returning the error; rollback would revive the session.
                self._revoke(db, row[0], now, 'device.refresh_reuse')
                error = DeviceError('invalid_grant', 401)
            elif db.execute('SELECT COUNT(*) FROM device_refresh WHERE device_id=?', (row[0],)).fetchone()[0] >= 10000:
                self._revoke(db, row[0], now, 'device.rotation_limit')
                error = DeviceError('reauthorization_required', 401)
            else:
                db.execute('UPDATE device_refresh SET used=1 WHERE digest=?', (token_hash(token),))
                result = self._issue(db, row[0], now, row[1])
        if error:
            raise error
        return result

    def authenticate(self, token):
        now = int(self.clock())
        with self.store._db() as db:
            row = db.execute('SELECT d.id,d.label,d.account_id,d.account_name FROM device_access a JOIN devices d ON a.device_id=d.id '
                             'WHERE a.digest=? AND a.expires_at>? AND d.expires_at>? AND d.revoked=0',
                             (token_hash(token), now, now)).fetchone()
            if row and row[2] and not db.execute('SELECT 1 FROM member_accounts WHERE subject=? AND disabled=0',(row[2],)).fetchone():
                row=None
        if not row:
            raise DeviceError('invalid_token', 401)
        return {'device_id': row[0], 'label': row[1], 'server_id': self.identity(), 'scope': 'device:read',
                'account_id':row[2], 'account_name':row[3]}

    def list(self):
        now = int(self.clock())
        with self.store._db() as db:
            return [dict(zip(('device_id','label','created_at','expires_at','revoked','account_id','account_name'), row))
                    for row in db.execute('SELECT id,label,created_at,expires_at,revoked,account_id,account_name '
                                          'FROM devices WHERE expires_at>? ORDER BY created_at DESC', (now,))]

    @staticmethod
    def _revoke(db, device_id, now, event):
        from .wireguard import revoke_enrollment
        revoke_enrollment(db, device_id, now)
        db.execute('UPDATE devices SET revoked=1 WHERE id=?', (device_id,))
        db.execute('DELETE FROM device_access WHERE device_id=?', (device_id,))
        db.execute('DELETE FROM device_refresh WHERE device_id=?', (device_id,))
        db.execute('INSERT INTO audit(event,created_at) VALUES(?,?)', (event, now))

    def revoke(self, device_id):
        with self.store._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM devices WHERE id=?', (device_id,)).fetchone():
                raise DeviceError('unknown_device', 404)
            self._revoke(db, device_id, int(self.clock()), 'device.revoked')
        return {'revoked': True}
