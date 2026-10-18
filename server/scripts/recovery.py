"""Offline, streamed age-encrypted backup. Restore into a NEW directory only.

Stop both containers first. The caller verifies they are stopped. Run from the
maintenance container or on an offline copy; never archive running databases.
No media, cache or recovery private key is included. age provides authenticated
stream encryption; tar members are individually validated before extraction.
"""
from __future__ import annotations
import argparse
import io
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

FORMAT = 1
MAX_BYTES = 100 * 1024**3


def check_sqlite(path):
    with sqlite3.connect(path) as db:
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('Base SQLite inválida.')


def validate_state(state):
    nova = state/'nova/nova.sqlite3'
    if not nova.is_file():
        raise ValueError('Falta a base NOVA; não é um estado inicializado.')
    check_sqlite(nova)
    with sqlite3.connect(nova) as db:
        if db.execute('PRAGMA user_version').fetchone()[0] > 1:
            raise ValueError('Schema NOVA mais recente que esta ferramenta.')
        if db.execute('SELECT COUNT(*) FROM admin').fetchone()[0] != 1:
            raise ValueError('Conclui primeiro a criação do proprietário.')
    databases = list((state/'jellyfin/config').rglob('jellyfin.db'))
    if len(databases) != 1:
        raise ValueError('Esperada uma base jellyfin.db na configuração.')
    jf = databases[0]
    check_sqlite(jf)
    with sqlite3.connect(jf) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'Users', 'Devices', 'ApiKeys'}.issubset(tables):
            raise ValueError('Schema Jellyfin não suportado para recuperação segura.')
        if db.execute('SELECT COUNT(*) FROM Users').fetchone()[0] != 1:
            raise ValueError('M2 suporta recuperação de uma instalação com um único proprietário Jellyfin.')
    return nova, jf


def files_for_backup(state):
    state = Path(state).resolve(strict=True)
    files = []
    for folder in ('nova', 'jellyfin/config'):
        root = state/folder
        for path in sorted(root.rglob('*')):
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ValueError('Cópia recusada: links ou ficheiros especiais no estado.')
            if path.name == 'bootstrap.token' or 'log' in path.relative_to(state).parts:
                continue
            if path.is_file():
                files.append(path)
    if sum(path.stat().st_size for path in files) > MAX_BYTES:
        raise ValueError('Estado excede o limite de 100 GiB.')
    return state, files


def backup(state, destination, recipient, *, deployment, stopped=False, age='age'):
    if not stopped:
        raise ValueError('Parar ambos os serviços e confirmar --services-stopped.')
    if not recipient.startswith('age1') or not recipient.isalnum():
        raise ValueError('Requer destinatário público age X25519; nunca a chave privada.')
    state, files = files_for_backup(state)
    # Database checks may checkpoint WAL; backup source needs rw access while stopped.
    validate_state(state)
    files = files_for_backup(state)[1]
    destination = Path(destination).resolve()
    if destination == state or state in destination.parents:
        raise ValueError('Guardar a cópia fora do estado de execução.')
    # Record deployment data inside encryption, never execute it during restore.
    manifest = json.dumps({'format': FORMAT, 'nova_schema': 1,
                           'deployment': Path(deployment).read_text(encoding='utf8')}).encode()
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            process = subprocess.Popen([age, '--encrypt', '--recipient', recipient],
                                       stdin=subprocess.PIPE, stdout=output, stderr=subprocess.DEVNULL)
            try:
                with tarfile.open(fileobj=process.stdin, mode='w|') as archive:
                    item = tarfile.TarInfo('manifest.json'); item.size = len(manifest); item.mode = 0o600
                    archive.addfile(item, io.BytesIO(manifest))
                    for path in files:
                        archive.add(path, arcname='state/'+path.relative_to(state).as_posix(), recursive=False)
                process.stdin.close()
                if process.wait() != 0:
                    raise ValueError('Encriptação age falhou.')
                output.flush(); os.fsync(output.fileno())
            finally:
                if process.poll() is None:
                    process.kill(); process.wait()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return {'encrypted': True, 'files': len(files), 'media_included': False}


def extract_checked(stream, staging):
    total = 0; seen = set(); manifest = None
    with tarfile.open(fileobj=stream, mode='r|') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts or '\\' in member.name or \
                    str(path) != member.name or member.name in seen:
                raise ValueError('Membro inseguro ou repetido no arquivo.')
            seen.add(member.name)
            if len(seen) > 1_000_000 or member.size < 0:
                raise ValueError('Limite do arquivo excedido.')
            total += member.size
            if total > MAX_BYTES:
                raise ValueError('Limite de restauro excedido.')
            source = archive.extractfile(member)
            if member.name == 'manifest.json':
                if member.size > 1024*1024:
                    raise ValueError('Manifesto demasiado grande.')
                manifest = json.load(source)
                if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or manifest.get('nova_schema') != 1:
                    raise ValueError('Versão de cópia não suportada.')
                continue
            if not (member.name.startswith('state/nova/') or member.name.startswith('state/jellyfin/config/')):
                raise ValueError('Caminho fora do estado permitido.')
            if path.name == 'bootstrap.token':
                raise ValueError('Token de bootstrap não permitido no restauro.')
            target = staging.joinpath(*path.parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open('xb') as output:
                os.chmod(target, 0o600)
                shutil.copyfileobj(source, output, 1024*1024)
    if manifest is None:
        raise ValueError('Falta manifesto.')
    # Consume the authenticated age stream, including the final chunk/tag.
    while stream.read(1024*1024):
        pass
    return manifest


def revoke_restored_sessions(state):
    nova, jf = validate_state(state)
    with sqlite3.connect(nova) as db:
        db.execute('DELETE FROM sessions')
        db.execute('UPDATE jellyfin_setup SET lease=NULL,lease_until=0,report=NULL')
        db.execute("INSERT INTO audit(event,created_at) VALUES('recovery.sessions_revoked',strftime('%s','now'))")
    with sqlite3.connect(jf) as db:
        db.execute('DELETE FROM Devices')
        db.execute('DELETE FROM ApiKeys')
    # Volatile Jellyfin cache is deliberately rebuilt.
    (state/'jellyfin/cache').mkdir(mode=0o700, parents=True, exist_ok=True)


def restore(archive, destination, identity, *, age='age'):
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Restaurar apenas para uma pasta nova; nunca sobrepor uma instalação.')
    parent = destination.parent.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='.nova-restore-', dir=parent) as folder:
        staging = Path(folder)
        process = subprocess.Popen([age, '--decrypt', '--identity', str(identity), str(archive)],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            manifest = extract_checked(process.stdout, staging)
            if process.wait() != 0:
                raise ValueError('Chave incorreta ou cópia alterada/incompleta.')
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill(); process.wait()
        revoke_restored_sessions(staging/'state')
        (staging/'deployment.original.txt').write_text(manifest['deployment'], encoding='utf8')
        # mkdir reserves the destination without overwriting an existing path.
        destination.mkdir(mode=0o700)
        for child in list(staging.iterdir()):
            child.rename(destination/child.name)
    return {'restored': True, 'sessions_revoked': True, 'requires_fresh_login': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('backup')
    create.add_argument('--state', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--recipient', required=True)
    create.add_argument('--deployment', type=Path, required=True)
    create.add_argument('--services-stopped', action='store_true')
    recover = sub.add_parser('restore')
    recover.add_argument('--input', type=Path, required=True)
    recover.add_argument('--output', type=Path, required=True)
    recover.add_argument('--identity', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'backup':
        result = backup(args.state, args.output, args.recipient, deployment=args.deployment,
                        stopped=args.services_stopped)
    else:
        result = restore(args.input, args.output, args.identity)
    print(json.dumps(result))
