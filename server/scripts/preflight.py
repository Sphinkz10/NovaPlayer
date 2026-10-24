#!/usr/bin/env python3
"""Read-only Linux lab checks. Never installs packages or modifies NAS settings."""
from __future__ import annotations
import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path

try:
    from .install import ROOT, validate_layout
except ImportError:
    from install import ROOT, validate_layout


def inspect(a, b, root=ROOT):
    checks = []
    def check(name, ok, detail):
        checks.append({'check': name, 'ok': bool(ok), 'detail': detail})
    check('linux', platform.system() == 'Linux', platform.system())
    check('architecture', platform.machine().lower() in ('x86_64', 'aarch64', 'arm64'), platform.machine())
    uid = os.getuid() if hasattr(os, 'getuid') else None
    check('service_user', uid is not None and uid != 0, 'Requer uma conta de serviço sem root.')
    version = Path('/etc/version')
    release = version.read_text(encoding='utf8').strip()[:160] if version.is_file() else platform.release()
    try:
        validate_layout(a, b, root)
        check('media_paths', True, 'Duas origens distintas, acessíveis à conta atual e separadas do pacote.')
    except (OSError, ValueError) as exc:
        check('media_paths', False, str(exc))
    state = root/'state'
    fresh = not (root/'.env').exists() and not (state.exists() and any(state.iterdir()))
    check('fresh_install', fresh, 'Instalações existentes devem ser retomadas; não voltar a executar install.py.')
    check('package_writable', os.access(root, os.W_OK | os.X_OK), 'Permissão da conta atual na pasta do pacote.')
    for port in (8787, 8096):
        try:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', port))
            check('port_'+str(port), True, 'Porta loopback disponível.')
        except OSError:
            check('port_'+str(port), False, 'Porta indisponível ou já ocupada.')
    docker = shutil.which('docker')
    for name, args in [('docker_engine', ['info', '--format', '{{.ServerVersion}}']),
                       ('docker_compose', ['compose', 'version', '--short'])]:
        try:
            if not docker:
                raise FileNotFoundError()
            result = subprocess.run([docker, *args], capture_output=True, text=True, timeout=10)
            check(name, result.returncode == 0, result.stdout.strip()[:80] if result.returncode == 0
                  else 'Docker indisponível ou sem autorização para esta conta.')
        except (OSError, subprocess.TimeoutExpired):
            check(name, False, 'Docker não encontrado ou não respondeu.')
    return {'ready_for_linux_lab': all(c['ok'] for c in checks), 'host_release': release,
            'truenas_certified': False, 'checks': checks,
            'remaining': ['Validar versão e método suportado pelas Apps TrueNAS.',
                          'Validar ACL dentro dos contentores; a conta host não prova acesso do contentor.',
                          'Medir espaço, desempenho, reinício e backup/restauro no servidor real.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Verificar pré-requisitos sem alterar o servidor.')
    parser.add_argument('--media-a', required=True)
    parser.add_argument('--media-b', required=True)
    args = parser.parse_args()
    report = inspect(args.media_a, args.media_b)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['ready_for_linux_lab'] else 1)
