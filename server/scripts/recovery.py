"""Offline, streamed age-encrypted backup. Restore into a NEW directory only.

Stop all deployment containers first. The caller verifies they are stopped. Run from the
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
import sys
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path, PurePosixPath

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

FORMAT = 1
LAN_FORMAT = 2
WIREGUARD_FORMAT = 3
MAX_BYTES = 100 * 1024**3


def check_sqlite(path):
    with closing(sqlite3.connect(path)) as db,db:
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('Base SQLite inválida.')


def validate_state(state):
    nova = state/'nova/nova.sqlite3'
    if not nova.is_file():
        raise ValueError('Falta a base NOVA; não é um estado inicializado.')
    check_sqlite(nova)
    with closing(sqlite3.connect(nova)) as db,db:
        schema=db.execute('PRAGMA user_version').fetchone()[0]
        if schema > 3:
            raise ValueError('Schema NOVA mais recente que esta ferramenta.')
        if db.execute('SELECT COUNT(*) FROM admin').fetchone()[0] != 1:
            raise ValueError('Conclui primeiro a criação do proprietário.')
    databases = list((state/'jellyfin/config').rglob('jellyfin.db'))
    if len(databases) != 1:
        raise ValueError('Esperada uma base jellyfin.db na configuração.')
    jf = databases[0]
    check_sqlite(jf)
    with closing(sqlite3.connect(jf)) as db,db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'Users', 'Devices', 'ApiKeys'}.issubset(tables):
            raise ValueError('Schema Jellyfin não suportado para recuperação segura.')
        users={str(row[0]).replace('-','').lower() for row in db.execute('SELECT Id FROM Users')}
    with closing(sqlite3.connect(nova)) as db,db:
        managed={str(row[0]).replace('-','').lower() for row in db.execute(
            'SELECT DISTINCT jellyfin_user FROM member_accounts WHERE jellyfin_user IS NOT NULL')} if schema>=3 else set()
    if not managed.issubset(users) or len(users-managed)!=1:
        raise ValueError('Recuperação exige o proprietário e apenas utilizadores Jellyfin geridos pela NOVA.')
    return nova, jf


def is_lan(state):
    return any((state/name).exists() or (state/name).is_symlink() for name in ('directory','identity'))


def files_for_backup(state):
    state = Path(state).resolve(strict=True)
    files = []
    folders=('nova','jellyfin/config')+(('directory','identity') if is_lan(state) else ())
    for folder in folders:
        root = state/folder
        for component in (state/'nova', state/'jellyfin', state/'jellyfin/config',state/'directory',state/'identity',state/'gateway'):
            if component.is_symlink():
                raise ValueError('Cópia recusada: links nos diretórios de estado.')
        for path in sorted(root.rglob('*')):
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)) or \
                    (stat.S_ISREG(mode) and path.stat().st_nlink != 1):
                raise ValueError('Cópia recusada: links ou ficheiros especiais no estado.')
            if path.name == 'bootstrap.token' or path.name.endswith(('.sqlite3-shm','.db-shm')) or 'log' in path.relative_to(state).parts:
                continue
            if ':' in path.relative_to(state).as_posix() or '\\' in path.relative_to(state).as_posix():
                raise ValueError('Nome de ficheiro não suportado num arquivo de recuperação portátil.')
            if path.is_file():
                files.append(path)
    if sum(path.stat().st_size for path in files) > MAX_BYTES:
        raise ValueError('Estado excede o limite de 100 GiB.')
    return state, files


def backup(state, destination, recipient, *, deployment, stopped=False, age='age'):
    if not stopped:
        raise ValueError('Parar todos os serviços e confirmar --services-stopped.')
    if not recipient.startswith('age1') or not recipient.isalnum():
        raise ValueError('Requer destinatário público age X25519; nunca a chave privada.')
    state, files = files_for_backup(state)
    # Database checks may checkpoint WAL; backup source needs rw access while stopped.
    validate_state(state)
    deployment_text=Path(deployment).read_text(encoding='utf8')
    profile=is_lan(state)
    from scripts.wireguard_recovery import is_wireguard
    wireguard=is_wireguard(state)
    if wireguard and not profile:raise ValueError('Identidade LAN/WireGuard incompleta.')
    if not profile and 'nova_server.lan_launch' in deployment_text:
        raise ValueError('Deployment LAN sem Directory/identidades completos; cópia recusada.')
    if not wireguard and 'nova-gateway' in deployment_text:
        raise ValueError('Deployment WireGuard sem identidade completa; cópia recusada.')
    if profile:
        from scripts.lan_recovery import validate_lan,deployment_values
        validate_lan(state,wireguard=wireguard);deployment_values(state,deployment_text,wireguard=wireguard)
    destination = Path(destination).resolve()
    if destination == state or state in destination.parents:
        raise ValueError('Guardar a cópia fora do estado de execução.')
    # Record deployment data inside encryption, never execute it during restore.
    with closing(sqlite3.connect(state/'nova/nova.sqlite3')) as db,db:
        schema = db.execute('PRAGMA user_version').fetchone()[0]
    selected_format=WIREGUARD_FORMAT if wireguard else LAN_FORMAT if profile else FORMAT
    manifest = json.dumps({'format': selected_format, 'nova_schema': schema,
                           'deployment': deployment_text}).encode()
    if len(manifest)>1024*1024:raise ValueError('Manifesto demasiado grande.')
    # All SQLite connections must be closed before the final file snapshot.
    files=files_for_backup(state)[1]
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
    return {'encrypted': True, 'files': len(files), 'media_included': False,
            'profile':'wireguard' if wireguard else 'lan' if profile else 'legacy','format':selected_format}


def extract_checked(stream, staging):
    total = 0; seen = set(); manifest = None
    with tarfile.open(fileobj=stream, mode='r|') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts or '\\' in member.name or ':' in member.name or \
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
                if (not isinstance(manifest, dict) or type(manifest.get('format')) is not int or
                    manifest['format'] not in (FORMAT,LAN_FORMAT,WIREGUARD_FORMAT) or type(manifest.get('nova_schema')) is not int or
                    manifest['nova_schema'] not in (0,1,2,3) or not isinstance(manifest.get('deployment'),str)):
                    raise ValueError('Versão de cópia não suportada.')
                continue
            if not any(member.name.startswith('state/'+folder+'/') for folder in ('nova','jellyfin/config','directory','identity')):
                raise ValueError('Caminho fora do estado permitido.')
            if path.name == 'bootstrap.token':
                raise ValueError('Token de bootstrap não permitido no restauro.')
            target = staging.joinpath(*path.parts)
            parent=staging
            for part in path.parts[:-1]:
                parent=parent/part;parent.mkdir(mode=0o700,exist_ok=True)
            with target.open('xb') as output:
                os.chmod(target, 0o600)
                shutil.copyfileobj(source, output, 1024*1024)
    if manifest is None:
        raise ValueError('Falta manifesto.')
    if manifest['format']==FORMAT and any(name.startswith(('state/directory/','state/identity/')) for name in seen):
        raise ValueError('Estado LAN não permitido num arquivo legado.')
    # Consume the authenticated age stream, including the final chunk/tag.
    while stream.read(1024*1024):
        pass
    return manifest


def revoke_restored_sessions(state):
    nova, jf = validate_state(state)
    with closing(sqlite3.connect(nova)) as db,db:
        db.execute('DELETE FROM sessions')
        if db.execute('PRAGMA user_version').fetchone()[0] >= 2:
            db.execute('DELETE FROM device_access')
            db.execute('DELETE FROM device_refresh')
            db.execute('DELETE FROM device_requests')
            db.execute('UPDATE devices SET revoked=1')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wireguard_enrollments'").fetchone():
                db.execute("UPDATE wireguard_enrollments SET state='revoked',revision=revision+1,updated_at=strftime('%s','now')")
        if db.execute('PRAGMA user_version').fetchone()[0] >= 3:
            db.execute('DELETE FROM identity_assertions')
            db.execute('UPDATE member_accounts SET disabled=1,credential=NULL,revision=revision+1')
        db.execute('UPDATE jellyfin_setup SET lease=NULL,lease_until=0,report=NULL')
        db.execute("INSERT INTO audit(event,created_at) VALUES('recovery.sessions_revoked',strftime('%s','now'))")
        checks=['SELECT COUNT(*) FROM sessions']
        schema=db.execute('PRAGMA user_version').fetchone()[0]
        if schema>=2:checks+=['SELECT COUNT(*) FROM '+table for table in ('device_access','device_refresh','device_requests')]+['SELECT COUNT(*) FROM devices WHERE revoked=0']
        if schema>=3:checks+=['SELECT COUNT(*) FROM member_accounts WHERE disabled=0 OR credential IS NOT NULL']
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wireguard_enrollments'").fetchone():
            checks+=['SELECT COUNT(*) FROM wireguard_enrollments WHERE state!=\'revoked\'']
        if any(db.execute(query).fetchone()[0] for query in checks):raise ValueError('Revogação NOVA incompleta.')
    with closing(sqlite3.connect(jf)) as db,db:
        db.execute('DELETE FROM Devices')
        db.execute('DELETE FROM ApiKeys')
        if any(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('Devices','ApiKeys')):
            raise ValueError('Revogação Jellyfin incompleta.')
    control=state/'nova/directory-control.sqlite3'
    if control.is_file():
        with closing(sqlite3.connect(control)) as db,db:
            columns={row[1] for row in db.execute('PRAGMA table_info(publication)')}
            if 'renewal_credential' in columns:
                db.execute('UPDATE publication SET renewal_credential=NULL,renewal_expires_at=NULL')
    # Volatile Jellyfin cache is deliberately rebuilt.
    (state/'jellyfin/cache').mkdir(mode=0o700, parents=True, exist_ok=True)


def restore(archive, destination, identity, *, age='age',lan_state_root=None,image=None,gateway_image=None):
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
        wireguard=manifest['format']==WIREGUARD_FORMAT
        profile=manifest['format'] in (LAN_FORMAT,WIREGUARD_FORMAT)
        if not wireguard and gateway_image:raise ValueError('Imagem gateway só é aplicável a uma cópia WireGuard.')
        if wireguard and not gateway_image:raise ValueError('Restauro WireGuard exige --gateway-image ou --gateway-image-file.')
        if not profile and (lan_state_root or image):raise ValueError('Arquivo legado; opções LAN não são aplicáveis.')
        if profile:
            if not lan_state_root or not image:raise ValueError('Restauro LAN exige --lan-state-root e a imagem desta entrega (--image ou --image-file).')
            if manifest['nova_schema']!=3:raise ValueError('Schema LAN não suportado.')
            from scripts.lan_recovery import write_restored_guidance,revoke_lan
            report=write_restored_guidance(staging,manifest,state_root=lan_state_root,image=image,gateway_image=gateway_image)
        elif is_lan(staging/'state'):
            raise ValueError('Estado LAN não permitido num arquivo legado.')
        revoke_restored_sessions(staging/'state')
        if profile:revoke_lan(staging/'state')
        if wireguard:
            from scripts.wireguard_recovery import revoke_gateway_runtime
            revoke_gateway_runtime(staging/'state')
        (staging/'deployment.original.txt').write_text(manifest['deployment'], encoding='utf8')
        (staging/'deployment.original.txt').chmod(0o600)
        # mkdir reserves the destination without overwriting an existing path.
        destination.mkdir(mode=0o700)
        for child in list(staging.iterdir()):
            child.rename(destination/child.name)
    return {'restored': True, 'sessions_revoked': True, 'requires_fresh_login': True,
            'profile':'wireguard' if wireguard else 'lan' if profile else 'legacy',
            **({'identity_preserved':True,'requires_republication':True,'tls_rotation_required':report['tls_rotation_required']} if profile else {})}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('backup')
    create.add_argument('--state', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--recipient', required=True)
    create.add_argument('--deployment', type=Path, required=True)
    create.add_argument('--services-stopped', action='store_true')
    create.add_argument('--age',default='age',help='Executável age; fornecido pela imagem de manutenção NOVA')
    recover = sub.add_parser('restore')
    recover.add_argument('--input', type=Path, required=True)
    recover.add_argument('--output', type=Path, required=True)
    recover.add_argument('--identity', type=Path, required=True)
    recover.add_argument('--age',default='age')
    recover.add_argument('--lan-state-root',help='Novo dataset /mnt/POOL/PASTA para o YAML LAN; não acede ao NAS')
    images=recover.add_mutually_exclusive_group()
    images.add_argument('--image');images.add_argument('--image-file',type=Path)
    gateways=recover.add_mutually_exclusive_group()
    gateways.add_argument('--gateway-image');gateways.add_argument('--gateway-image-file',type=Path)
    args = parser.parse_args()
    if args.command == 'backup':
        result = backup(args.state, args.output, args.recipient, deployment=args.deployment,
                        stopped=args.services_stopped,age=args.age)
    else:
        image=args.image or (args.image_file.read_text(encoding='ascii').strip() if args.image_file else None)
        gateway=args.gateway_image or (args.gateway_image_file.read_text(encoding='ascii').strip() if args.gateway_image_file else None)
        result = restore(args.input, args.output, args.identity,lan_state_root=args.lan_state_root,image=image,age=args.age,gateway_image=gateway)
    print(json.dumps(result))
