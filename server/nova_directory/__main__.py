"""Local operator commands. Passwords are read with getpass, never CLI arguments."""
import argparse
import getpass
import ssl
from pathlib import Path
from urllib.parse import urlsplit

from .protocol import private_origin
from .store import Registry, DirectoryError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('serve','account-add','account-disable'))
    parser.add_argument('--state', required=True)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--username')
    parser.add_argument('--certificate')
    parser.add_argument('--key')
    args = parser.parse_args()
    private_origin(args.origin)
    if args.action == 'serve':
        if not args.certificate or not args.key:
            parser.error('serve requires --certificate and --key')
        import uvicorn
        from .api import make_directory
        config = uvicorn.Config(make_directory(args.state, args.origin), host='127.0.0.1',
            port=urlsplit(args.origin).port, ssl_certfile=str(Path(args.certificate).resolve(strict=True)),
            ssl_keyfile=str(Path(args.key).resolve(strict=True)), proxy_headers=False, access_log=False)
        config.load()
        config.ssl.minimum_version = ssl.TLSVersion.TLSv1_3
        uvicorn.Server(config).run()
    else:
        if not args.username:
            parser.error('Account command requires --username')
        registry = Registry(args.state, args.origin)
        if args.action == 'account-add':
            password = getpass.getpass('Palavra-passe da nova conta: ')
            if password != getpass.getpass('Confirmar palavra-passe: '):
                raise ValueError('As palavras-passe não coincidem.')
            registry.create_account(args.username, password)
            print('Conta criada no Directory de laboratório.')
        else:
            registry.disable_account(args.username)
            print('Conta desativada; sessões e descoberta bloqueadas.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, DirectoryError, OSError):
        raise SystemExit('Operação recusada. Verifica os argumentos, a conta e os ficheiros locais.') from None
