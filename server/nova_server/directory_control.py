"""Optional owner-only Directory integration. No background renewal or saved credentials."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import httpx
from cryptography.exceptions import InvalidSignature

from nova_directory.client import DirectoryClient, server_identity
from nova_directory.protocol import Descriptor, encode, private_origin, verify_record


class ControlError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status


class DirectoryControl:
    def __init__(self, state, origin, ca, client_origin, certificate):
        self.state = Path(state)
        self.origin = private_origin(origin)
        self.client_origin = private_origin(client_origin)
        self.ca, self.certificate = Path(ca), Path(certificate)
        # Operator-selected files only. Requests can never select paths or hosts.
        if not self.ca.is_file() or self.ca.stat().st_size > 12000:
            raise ValueError('Invalid Directory trust file')
        with DirectoryClient(self.origin, self.ca).http:
            pass  # Parse TLS trust without making a network request.
        self.path = self.state/'directory-control.sqlite3'
        with self.db() as db:
            if db.execute('PRAGMA user_version').fetchone()[0] > 1:
                raise ValueError('Newer Directory Control schema')
            db.execute('CREATE TABLE IF NOT EXISTS publication (id INTEGER PRIMARY KEY CHECK(id=1), '
                       'origin TEXT NOT NULL, account TEXT, record TEXT, checked_at INTEGER, observation TEXT)')
            db.execute('INSERT OR IGNORE INTO publication(id,origin) VALUES(1,?)', (self.origin,))
            if db.execute('SELECT origin FROM publication WHERE id=1').fetchone()[0] != self.origin:
                raise ValueError('Directory identity is already bound to another origin')
            db.execute('PRAGMA user_version=1')
        self.path.chmod(0o600)

    @contextmanager
    def db(self, *, write=False):
        connection = sqlite3.connect(self.path, timeout=0)
        try:
            if write:
                connection.execute('BEGIN IMMEDIATE')
            with connection:
                yield connection
        except sqlite3.OperationalError:
            raise ControlError('directory_busy') from None
        finally:
            connection.close()

    def identity(self):
        sid, key = server_identity(self.state)
        public = key.public_key().public_bytes_raw()
        return sid, key, encode(public), hashlib.sha256(public).hexdigest()

    def status(self):
        result = {'enabled':True, 'origin':self.origin, 'state':'not_checked',
                  'identity':'missing', 'media_authorized':False, 'automatic_renewal':False}
        try:
            sid, _, public, fingerprint = self.identity()
            result.update(identity='ready', server_id=sid, fingerprint=fingerprint)
        except FileNotFoundError:
            return result
        except (ValueError, OSError, sqlite3.Error):
            return {**result, 'identity':'invalid', 'state':'identity_error'}
        with self.db() as db:
            record, checked, observation = db.execute(
                'SELECT record,checked_at,observation FROM publication WHERE id=1').fetchone()
        result.update(checked_at=checked, state=observation or 'not_checked')
        if record:
            record = json.loads(record)
            try:
                descriptor = verify_record(record, self.origin, expected_key=public,
                                           now=record['payload']['issued_at'])
                if descriptor.server_id != sid:
                    raise ValueError('Wrong server')
                result.update(entry_id=record['payload']['entry_id'], name=descriptor.name,
                              expires_at=record['payload']['expires_at'], version=record['payload']['version'])
                if result['expires_at'] <= time.time():
                    result['state'] = 'expired'
                else:
                    descriptor.check_certificate(time.time())
            except (ValueError, InvalidSignature, KeyError, TypeError):
                result['state'] = 'invalid_receipt'
        return result

    def initialize(self):
        with self.db(write=True) as db:
            if (not (self.state/'directory-signing.key').exists() and
                    db.execute('SELECT account FROM publication WHERE id=1').fetchone()[0]):
                raise ControlError('directory_identity_restore_required')
            server_identity(self.state, create_key=True)
        return self.status()

    def operate(self, action, username, password, name=None):
        sid, key, public, _ = self.identity()  # Never silently regenerate a missing key.
        with self.db(write=True) as db:
            client = DirectoryClient(self.origin, self.ca)
            try:
                client.login(username, password)
                pinned = db.execute('SELECT account FROM publication WHERE id=1').fetchone()[0]
                if pinned and pinned != client.account:
                    raise ControlError('directory_account_changed')
                db.execute('UPDATE publication SET account=? WHERE id=1', (client.account,))
                # Persist account continuity BEFORE a remote mutation, even if its response is lost.
                db.commit()
                db.execute('BEGIN IMMEDIATE')
                if action == 'publish':
                    if self.certificate.stat().st_size > 6000:
                        raise ValueError('Certificate too large')
                    descriptor = Descriptor(server_id=sid, name=name, client_origin=self.client_origin,
                        certificate_pem=self.certificate.read_text(encoding='ascii'))
                    previous = db.execute('SELECT record FROM publication WHERE id=1').fetchone()[0]
                    record = client.register(descriptor, key,
                        previous=json.loads(previous)['payload'] if previous else None)
                    observation = 'published_at_check'
                else:
                    matches = [entry['record'] for entry in client.discover()['servers']
                        if entry['record']['payload']['owner_id'] == client.account and
                           entry['record']['payload']['descriptor']['server_id'] == sid]
                    if len(matches) > 1:
                        raise ValueError('Ambiguous identity')
                    record = matches[0] if matches else None
                    if record:
                        verify_record(record, self.origin, expected_key=public)
                        previous = db.execute('SELECT record FROM publication WHERE id=1').fetchone()[0]
                        if previous:
                            old = json.loads(previous)['payload']
                            new = record['payload']
                            if old['entry_id'] != new['entry_id'] or new['version'] < old['version']:
                                raise ControlError('directory_revision_changed')
                    observation = 'listed_at_check' if record else 'not_listed_at_check'
                # Retain the last signed receipt when absent remotely, for continuity checks.
                db.execute('UPDATE publication SET record=COALESCE(?,record),checked_at=?,observation=? WHERE id=1',
                           (json.dumps(record) if record else None, int(time.time()), observation))
            finally:
                client.close()
        return self.status()


def safe_operation(operation):
    try:
        return operation()
    except ControlError:
        raise
    except (ValueError, OSError, sqlite3.Error, httpx.HTTPError, InvalidSignature, KeyError, TypeError):
        # No remote error, path, password, token, or certificate is reflected to the browser.
        raise ControlError('directory_operation_refused', 502) from None
