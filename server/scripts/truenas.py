"""Generate standalone Compose YAML (JSON subset) for TrueNAS Custom Apps.

Runs on the owner's PC; does not access or modify the NAS. No host packages needed.
"""
import argparse
import json
import re
from pathlib import Path, PurePosixPath

JELLYFIN_IMAGE = 'jellyfin/jellyfin:12.2.20261005-225228'


def path_value(raw):
    path = PurePosixPath(raw)
    if not re.fullmatch(r'/mnt/[A-Za-z0-9_./ -]+', raw) or '..' in path.parts or len(path.parts) < 4:
        raise ValueError('Usa um caminho de dataset absoluto /mnt/POOL/PASTA, sem .. ou caracteres especiais.')
    return path


def render(state_root, media_a, media_b, uid, gid, image, version):
    match = re.fullmatch(r'(\d{2})\.(\d{2})(?:\.\d+)*', version)
    if not match or tuple(map(int, match.groups())) < (24, 10):
        raise ValueError('Requer TrueNAS Community/SCALE 24.10+ com Apps Docker; indica uma versão estável.')
    if not 1 <= uid <= 2147483647 or not 1 <= gid <= 2147483647:
        raise ValueError('UID e GID devem pertencer a uma conta de serviço não root.')
    if not re.fullmatch(r'ghcr\.io/sphinkz10/nova-core@sha256:[0-9a-f]{64}', image):
        raise ValueError('Usa a imagem NOVA por digest fornecida no artefacto da CI.')
    roots = [path_value(raw) for raw in (state_root, media_a, media_b)]
    for index, first in enumerate(roots):
        for second in roots[index+1:]:
            if first == second or first in second.parents or second in first.parents:
                raise ValueError('Estado e origens devem ser três caminhos separados, sem sobreposição.')
    state, a, b = map(str, roots)
    def mount(source, target, read_only=False):
        return {'type': 'bind', 'source': source, 'target': target, 'read_only': read_only,
                'bind': {'create_host_path': False}}
    def service(image_name, port, volumes):
        return {'image': image_name, 'restart': 'unless-stopped', 'user': f'{uid}:{gid}',
                'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
                'ports': [f'127.0.0.1:{port}:{port}/tcp'], 'volumes': volumes,
                'networks': ['nova_internal']}
    jf = service(JELLYFIN_IMAGE, 8096, [mount(state+'/jellyfin/config', '/config'),
                mount(state+'/jellyfin/cache', '/cache'), mount(a, '/media/source-a', True),
                mount(b, '/media/source-b', True)])
    core = service(image, 8787, [mount(state+'/nova', '/data')])
    core.update({'read_only': True, 'tmpfs': ['/tmp:rw,noexec,nosuid,size=16m'],
                 'environment': {'NOVA_STATE_DIR': '/data', 'NOVA_JELLYFIN_URL': 'http://jellyfin:8096'},
                 'depends_on': ['jellyfin']})
    return {'services': {'jellyfin': jf, 'nova-core': core},
            'networks': {'nova_internal': {'driver': 'bridge'}}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('state-root', 'media-a', 'media-b', 'image', 'version', 'output'):
        parser.add_argument('--'+field, required=True)
    parser.add_argument('--uid', type=int, required=True)
    parser.add_argument('--gid', type=int, required=True)
    args = parser.parse_args()
    config = render(args.state_root, args.media_a, args.media_b, args.uid, args.gid, args.image, args.version)
    with Path(args.output).open('x', encoding='utf8', newline='\n') as output:
        json.dump(config, output, ensure_ascii=False, indent=2)
        output.write('\n')
    print('YAML criado. Preparar datasets/ACL no TrueNAS e instalar pelas Apps. Portas limitadas a loopback.')
