"""Public-key enrollment, not a gateway installer or a tunnel-state oracle.

Only the associated device can create its immutable enrollment. Approval never
claims a peer is installed. No private keys, command strings, routes or interface
names are accepted. Reassociation, not an unauthenticated rekey, resets a device.
"""
import base64
import binascii
import hashlib
import time

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from pydantic import ConfigDict, Field, field_validator

from .device_api import Payload
from .devices import DeviceError
from .security import token_hash


def validate_public_key(value):
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) != 32 or base64.b64encode(raw).decode('ascii') != value or raw[31] & 128:
            raise ValueError()
        # Reject noncanonical field elements and low-order points (zero shared secret).
        if int.from_bytes(raw, 'little') >= 2**255-19:
            raise ValueError()
        X25519PrivateKey.from_private_bytes(bytes(range(32))).exchange(X25519PublicKey.from_public_bytes(raw))
    except (ValueError, binascii.Error, TypeError):
        raise ValueError('Invalid WireGuard public key') from None
    return value


class Enrollment(Payload):
    model_config = ConfigDict(extra='forbid', strict=True)
    public_key: str = Field(min_length=44, max_length=44)
    _key = field_validator('public_key')(validate_public_key)


class EnrollmentDecision(Payload):
    revision: int = Field(strict=True, ge=1)
    approve: bool = Field(strict=True)


class WireGuardEnrollments:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    def _device(self, db, access, now):
        # Authentication and the mutation share one write transaction: a concurrent
        # revoke cannot leave an approved request behind an already revoked token.
        row = db.execute('SELECT d.id,d.account_id FROM devices d JOIN device_access a ON a.device_id=d.id '
                         'WHERE a.digest=? AND a.expires_at>? AND d.expires_at>? AND d.revoked=0',
                         (token_hash(access), now, now)).fetchone()
        if not row or (row[1] and not db.execute('SELECT 1 FROM member_accounts WHERE subject=? AND disabled=0', (row[1],)).fetchone()):
            raise DeviceError('invalid_token', 401)
        return row[0]

    @staticmethod
    def _view(db, device_id, now):
        row = db.execute('SELECT e.public_key,e.state,e.revision,e.created_at,e.updated_at,d.label,d.account_id,d.account_name,'
                         'd.revoked,d.expires_at FROM wireguard_enrollments e JOIN devices d ON d.id=e.device_id '
                         'WHERE e.device_id=?', (device_id,)).fetchone()
        if not row:
            return None
        key, state, revision, created, updated, label, account, name, revoked, expiry = row
        active = not revoked and expiry > now
        if account and not db.execute('SELECT 1 FROM member_accounts WHERE subject=? AND disabled=0', (account,)).fetchone():
            active = False
        if not active:
            state = 'revoked'
        return {'schema_version': 1, 'server_id': db.execute('SELECT server_id FROM server_identity WHERE id=1').fetchone()[0],
                'device_id': device_id, 'label': label, 'account_id': account, 'account_name': name,
                'public_key': key, 'fingerprint': hashlib.sha256(base64.b64decode(key)).hexdigest(),
                'state': state, 'revision': revision, 'created_at': created, 'updated_at': updated,
                'gateway_state': 'not_verified', 'remote_access_enabled': False}

    def request(self, access, key):
        validate_public_key(key)
        now = int(self.clock())
        with self.store._db() as db:
            db.execute('BEGIN IMMEDIATE')
            device = self._device(db, access, now)
            previous = db.execute('SELECT public_key FROM wireguard_enrollments WHERE device_id=?', (device,)).fetchone()
            if previous and previous[0] != key:
                raise DeviceError('wireguard_key_conflict', 409)
            if not previous:
                if db.execute('SELECT 1 FROM wireguard_enrollments WHERE public_key=?', (key,)).fetchone():
                    raise DeviceError('wireguard_key_conflict', 409)
                db.execute('INSERT INTO wireguard_enrollments(device_id,public_key,created_at,updated_at) VALUES(?,?,?,?)',
                           (device, key, now, now))
                db.execute("INSERT INTO audit(event,created_at) VALUES('wireguard.requested',?)", (now,))
            return self._view(db, device, now)

    def status(self, access):
        with self.store._db() as db:
            db.execute('BEGIN IMMEDIATE')
            device = self._device(db, access, int(self.clock()))
            result = self._view(db, device, int(self.clock()))
            if result is None:
                raise DeviceError('wireguard_enrollment_missing', 404)
            return result

    def list(self):
        with self.store._db() as db:
            return [self._view(db, row[0], int(self.clock())) for row in
                    db.execute('SELECT device_id FROM wireguard_enrollments ORDER BY created_at,device_id')]

    def decide(self, device, revision, approve):
        now = int(self.clock())
        with self.store._db() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self._view(db, device, now)
            if not current:
                raise DeviceError('wireguard_enrollment_missing', 404)
            if current['revision'] != revision or current['state'] == 'revoked':
                raise DeviceError('wireguard_enrollment_changed', 409)
            wanted = 'approved' if approve else 'revoked'
            if current['state'] != wanted:
                db.execute('UPDATE wireguard_enrollments SET state=?,revision=revision+1,updated_at=? WHERE device_id=?',
                           (wanted, now, device))
                db.execute('INSERT INTO audit(event,created_at) VALUES(?,?)',
                           ('wireguard.approved' if approve else 'wireguard.revoked', now))
            return self._view(db, device, now)

    def gateway_plan(self):
        """Public, atomic, short-lived desired set. No gateway credentials or routes."""
        now = int(self.clock())
        with self.store._db() as db:
            db.execute('BEGIN')
            server_id = db.execute('SELECT server_id FROM server_identity WHERE id=1').fetchone()[0]
            rows = db.execute('SELECT e.device_id,e.public_key,d.expires_at FROM wireguard_enrollments e '
                'JOIN devices d ON e.device_id=d.id WHERE e.state=\'approved\' AND d.revoked=0 AND d.expires_at>? '
                'AND (d.account_id IS NULL OR EXISTS(SELECT 1 FROM member_accounts m '
                'WHERE m.subject=d.account_id AND m.disabled=0)) ORDER BY e.device_id', (now,)).fetchall()
            return {'schema_version':1, 'server_id':server_id, 'issued_at':now,
                    'expires_at':min([now+15]+[row[2] for row in rows]),
                    'peers':[{'device_id':row[0], 'public_key':row[1]} for row in rows]}


def revoke_enrollment(db, device, now):
    db.execute("UPDATE wireguard_enrollments SET state='revoked',revision=revision+1,updated_at=? "
               "WHERE device_id=? AND state!='revoked'", (now, device))
