"""Read-only installation evidence; no passwords, file listings or environment dump.

Supply container IDs/names observed in TrueNAS Apps or docker compose ps.
Does not certify NAS reboot, backup or playback from a single healthy snapshot.
"""
import argparse
import datetime
import json
import platform
import re
import subprocess
from pathlib import Path


def inspect_container(reference):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', reference):
        raise ValueError('Identificador de contentor inválido.')
    result = subprocess.run(['docker','inspect',reference],check=True,capture_output=True,text=True,timeout=15)
    data = json.loads(result.stdout)
    if len(data) != 1:
        raise ValueError('Esperado um único contentor.')
    return data[0]


def summarize(core, jellyfin):
    checks = []
    for name, container in [('nova-core',core),('jellyfin',jellyfin)]:
        config = container['Config']; host = container['HostConfig']; state = container['State']
        ports = container['NetworkSettings'].get('Ports') or {}
        bound = [binding for values in ports.values() if values for binding in values]
        checks.extend([
            {'check': name+'.running', 'ok': state.get('Running') is True},
            {'check': name+'.healthy', 'ok': state.get('Health',{}).get('Status') == 'healthy'},
            {'check': name+'.loopback_only', 'ok': bool(bound) and all(b['HostIp']=='127.0.0.1' for b in bound)},
            {'check': name+'.non_root', 'ok': bool(re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*',config.get('User','')))},
            {'check': name+'.restricted', 'ok': not host.get('Privileged') and
                host.get('NetworkMode') != 'host' and 'ALL' in host.get('CapDrop',[])},
        ])
    for target in ('/media/source-a','/media/source-b'):
        mounts = [mount for mount in jellyfin['Mounts'] if mount['Destination']==target]
        checks.append({'check':target+'.read_only_mount','ok':len(mounts)==1 and mounts[0].get('RW') is False})
    checks.append({'check':'core_no_media_or_docker_socket','ok':all(
        not m['Destination'].startswith('/media') and 'docker.sock' not in m['Destination'] for m in core['Mounts'])})
    return {'snapshot_checks_passed':all(c['ok'] for c in checks), 'checks': checks,
            'images':{name:{'reference':c['Config']['Image'],'local_image_id':c['Image']}
                      for name,c in [('nova-core',core),('jellyfin',jellyfin)]}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-container',required=True)
    parser.add_argument('--jellyfin-container',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    report = summarize(inspect_container(args.core_container),inspect_container(args.jellyfin_container))
    report.update({'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'platform':platform.platform(), 'architecture':platform.machine(),
                   'truenas_version':Path('/etc/version').read_text().strip()[:160] if Path('/etc/version').is_file() else None,
                   'physical_acceptance_complete':False,
                   'remaining':['Configuração Control e indexação A/B','ACL e acesso aos ficheiros',
                                'Reinício do NAS','Origem indisponível','Backup/restauro','Atualização/reversão']})
    with args.output.open('x',encoding='utf8') as output:
        json.dump(report,output,ensure_ascii=False,indent=2)
    print(json.dumps({'snapshot_checks_passed':report['snapshot_checks_passed'],
                      'physical_acceptance_complete':False}))
    raise SystemExit(0 if report['snapshot_checks_passed'] else 1)
