#!/usr/bin/env python3
"""Install local NOVA Server bundle with paths validated before writing anything.

Use run as ordinary non-root service owner on Linux, with permission to run docker.
"""
from __future__ import annotations
import argparse
import os
import re
import secrets
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROHIBITED=('/','/etc','/proc','/sys','/dev','/root','/var/run')


def validate_media_path(raw: str) -> Path:
    if not raw or not raw.startswith('/'):
        raise ValueError('Indica um caminho absoluto de media Linux.')
    if not re.fullmatch(r'/[A-Za-z0-9_./ -]+',raw):
        raise ValueError('Caminho contém caracteres não suportados; usa letras, números, espaços, . _ - e /.')
    path=Path(raw).resolve(strict=True)
    forbidden = [Path(p).resolve() for p in PROHIBITED if p != '/']
    if not path.is_dir() or str(path) == '/' or any(p == path or p in path.parents for p in forbidden):
        raise ValueError('A origem tem de ser uma pasta de media existente, não um diretório de sistema.')
    if not os.access(path,os.R_OK|os.X_OK):
        raise ValueError('A pasta não é legível pelo utilizador atual.')
    return path


def validate_layout(a: str, b: str, root: Path=ROOT):
    source_a=validate_media_path(a)
    source_b=validate_media_path(b)
    if source_a == source_b or source_a in source_b.parents or source_b in source_a.parents:
        raise ValueError('Os diretórios não podem ser iguais nem conter um ao outro.')
    root = root.resolve()
    for source in (source_a, source_b):
        if source == root or source in root.parents or root in source.parents:
            raise ValueError('O pacote e os dados privados NOVA devem ficar separados das origens de media.')
    return source_a, source_b


def install(a: str,b: str,root:Path=ROOT, uid:int|None=None, gid:int|None=None) -> dict:
    source_a, source_b = validate_layout(a, b, root)
    if uid is None:uid=os.getuid()
    if gid is None:gid=os.getgid()
    if uid==0:
        raise ValueError('Instala com uma conta de serviço sem privilégios de root.')
    state=root/'state'
    env=root/'.env'
    boot=state/'nova'/'bootstrap.token'
    if env.exists() or boot.exists() or (state.exists() and any(state.iterdir())):
        raise FileExistsError('Instalação existente; não substituímos ficheiros de configuração ou credenciais.')
    for d in ('nova','jellyfin/config','jellyfin/cache'):
        folder=state/d
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        folder.chmod(0o700)
    # Environment and bootstrap token created exclusively from validated values.
    lines=[f'NOVA_UID={uid}',f'NOVA_GID={gid}',f'NOVA_MEDIA_A={source_a}',f'NOVA_MEDIA_B={source_b}']
    fd=os.open(env,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w',encoding='utf8') as stream:stream.write('\n'.join(lines)+'\n')
    fd=os.open(boot,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w',encoding='ascii') as stream:stream.write(secrets.token_urlsafe(48)+'\n')
    return {'env':str(env),'bootstrap_file':str(boot),'source_a':str(source_a),'source_b':str(source_b)}


def main():
    parser=argparse.ArgumentParser(description='Preparar pacote NOVA Server + Jellyfin (somente local).')
    parser.add_argument('--media-a',required=True)
    parser.add_argument('--media-b',required=True)
    args=parser.parse_args()
    try:r=install(args.media_a,args.media_b)
    except (ValueError,FileNotFoundError,FileExistsError,PermissionError) as e:parser.error(str(e))
    print('NOVA Server preparado sem expor portas na LAN/Internet.')
    print('Diretórios read-only:',r['source_a'],'+',r['source_b'])
    print('Executa agora: docker compose up -d --build')
    print('Depois: abrir http://127.0.0.1:8787 e criar o proprietário com state/nova/bootstrap.token.')
    print('A administração só funciona em 127.0.0.1 no servidor; consulta README.md.')

if __name__=='__main__':main()
