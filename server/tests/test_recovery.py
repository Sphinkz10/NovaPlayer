import io
import json
import os
import sqlite3
import tarfile
from pathlib import Path

import pytest
from nova_server.storage import Store, SCHEMA_VERSION
from nova_server.launch import initialize
from scripts.recovery import extract_checked, revoke_restored_sessions, backup, restore, files_for_backup
from scripts.truenas import render


def state_fixture(path):
    store = Store(path/'nova')
    store.bootstrap('owner', 'test-hash')
    store.save_session('old-token')
    config = path/'jellyfin/config/data'; config.mkdir(parents=True)
    with sqlite3.connect(config/'jellyfin.db') as db:
        db.executescript('CREATE TABLE Users(Id TEXT); INSERT INTO Users VALUES("owner");'
                        'CREATE TABLE Devices(Id TEXT); INSERT INTO Devices VALUES("old-device");'
                        'CREATE TABLE ApiKeys(Id TEXT); INSERT INTO ApiKeys VALUES("old-api-key");')
    return store


def test_restore_revokes_all_sessions_and_retains_owner(tmp_path):
    store = state_fixture(tmp_path)
    revoke_restored_sessions(tmp_path)
    assert store.has_admin() and not store.session_valid('old-token')
    with sqlite3.connect(tmp_path/'jellyfin/config/data/jellyfin.db') as db:
        assert db.execute('SELECT COUNT(*) FROM Devices').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM ApiKeys').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM Users').fetchone()[0] == 1


def test_recovery_refuses_multiple_jellyfin_accounts(tmp_path):
    state_fixture(tmp_path)
    with sqlite3.connect(tmp_path/'jellyfin/config/data/jellyfin.db') as db:
        db.execute('INSERT INTO Users VALUES("extra-user")')
    with pytest.raises(ValueError, match='único'):
        revoke_restored_sessions(tmp_path)


@pytest.mark.parametrize('name,kind', [('../escape', tarfile.REGTYPE),
    ('/absolute',tarfile.REGTYPE),('state/nova/link',tarfile.SYMTYPE),
    ('state/nova/hard',tarfile.LNKTYPE),('state/nova/pipe',tarfile.FIFOTYPE),
    ('state/nova/../outside',tarfile.REGTYPE),('state/nova/bootstrap.token',tarfile.REGTYPE),
    ('state/jellyfin/cache/data',tarfile.REGTYPE),('state\\nova\\file',tarfile.REGTYPE),
    ('state/nova/C:/escape',tarfile.REGTYPE)])
def test_reject_malicious_archive(tmp_path, name, kind):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as archive:
        item = tarfile.TarInfo(name); item.type=kind; item.size=0
        archive.addfile(item,io.BytesIO())
    stream.seek(0)
    with pytest.raises(ValueError):
        extract_checked(stream,tmp_path)


def test_duplicate_archive_member_rejected(tmp_path):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as archive:
        for _ in range(2):
            archive.addfile(tarfile.TarInfo('state/nova/file'),io.BytesIO())
    stream.seek(0)
    with pytest.raises(ValueError,match='repetido'):
        extract_checked(stream,tmp_path)


def test_restore_never_overwrites_existing_directory(tmp_path):
    original = tmp_path/'keep'; original.write_text('original')
    with pytest.raises(FileExistsError):
        restore('missing.age',tmp_path,'missing.key')
    assert original.read_text() == 'original'


def test_backup_requires_stopped_services(tmp_path):
    with pytest.raises(ValueError,match='Parar'):
        backup(tmp_path,tmp_path/'out','age1test',deployment='unused')


def test_hard_link_backup_refused(tmp_path):
    state_fixture(tmp_path)
    original = tmp_path/'nova/file'; original.write_text('private')
    os.link(original,tmp_path/'nova/alias')
    with pytest.raises(ValueError,match='links'):
        files_for_backup(tmp_path)


def test_container_bootstrap_is_idempotent(tmp_path):
    initialize(tmp_path)
    original = (tmp_path/'bootstrap.token').read_bytes()
    initialize(tmp_path)
    assert (tmp_path/'bootstrap.token').read_bytes() == original
    Store(tmp_path).bootstrap('owner','hash')
    (tmp_path/'bootstrap.token').unlink()
    initialize(tmp_path)
    assert not (tmp_path/'bootstrap.token').exists()


def test_schema_forward_guard_and_legacy_upgrade(tmp_path):
    store = Store(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute('PRAGMA user_version=0')
    Store(tmp_path)
    with sqlite3.connect(store.path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        db.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError,match='mais recente'):
        Store(tmp_path)


def test_truenas_standalone_config():
    config = render('/mnt/pool/nova','/mnt/pool/films','/mnt/pool/series',568,568,
                    'ghcr.io/sphinkz10/nova-core@sha256:'+'a'*64,'25.10.5')
    assert '${' not in json.dumps(config) and 'build' not in config['services']['nova-core']
    for service in config['services'].values():
        assert service['user']=='568:568'
        assert all(port.startswith('127.0.0.1:') for port in service['ports'])
        assert all(mount['bind']['create_host_path'] is False for mount in service['volumes'])
    assert all(mount['read_only'] for mount in config['services']['jellyfin']['volumes'][-2:])


@pytest.mark.parametrize('state,a,b,uid,version', [
    ('/mnt/pool/nova','/mnt/pool/nova/media','/mnt/pool/b',568,'25.10'),
    ('/mnt/pool/nova','/mnt/pool/a','/mnt/pool/a',568,'25.10'),
    ('/mnt/pool/nova','/mnt/pool/a','/mnt/pool/b',0,'25.10'),
    ('/mnt/pool/nova','/mnt/pool/a','/mnt/pool/b',568,'24.04'),
    ('/mnt/pool/nova','/mnt/pool/../etc','/mnt/pool/b',568,'25.10'),
])
def test_truenas_rejects_unsafe_layout(state,a,b,uid,version):
    with pytest.raises(ValueError):
        render(state,a,b,uid,568,'ghcr.io/sphinkz10/nova-core@sha256:'+'a'*64,version)
