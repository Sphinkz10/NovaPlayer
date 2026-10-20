"""Bind a device request to an account authenticated by the configured Directory."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

from cryptography.exceptions import InvalidSignature
from nova_directory.identity import verify_assertion
from .devices import DeviceError


def verify_device_assertion(state, server, assertion, *, now=None):
    try:
        path=Path(state).resolve(strict=True)/'directory-control.sqlite3'
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            origin,raw,public=db.execute('SELECT origin,record,issuer_public FROM publication WHERE id=1').fetchone()
        core=Path(state).resolve(strict=True)/'nova.sqlite3'
        with closing(sqlite3.connect(core.as_uri()+'?mode=ro',uri=True)) as db:
            barrier=None
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='identity_recovery_barrier'").fetchone():
                row=db.execute('SELECT not_before FROM identity_recovery_barrier WHERE id=1').fetchone()
                if not row or type(row[0]) is not int or row[0]<0:raise ValueError('Invalid recovery barrier')
                barrier=row[0]
        if not raw or not public:raise ValueError('Directory publication required')
        record=json.loads(raw)['payload']
        if record['descriptor']['server_id']!=server:raise ValueError('Wrong server')
        verified=verify_assertion(assertion,public,origin,record['entry_id'],server,
                                  int(time.time() if now is None else now))
        if barrier is not None and verified['issued_at']<=barrier:raise ValueError('Identity proof predates recovery')
        return verified
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,InvalidSignature):
        raise DeviceError('invalid_directory_identity',403) from None
