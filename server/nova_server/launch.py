"""Container first start: initialize owner bootstrap without logging the secret."""
import os
import secrets
from pathlib import Path

from .storage import Store


def initialize(path):
    state = Path(path)
    store = Store(state)
    if not store.has_admin():
        try:
            fd = os.open(state/'bootstrap.token', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return
        with os.fdopen(fd, 'w', encoding='ascii') as output:
            output.write(secrets.token_urlsafe(48)+'\n')


if __name__ == '__main__':
    initialize(os.environ.get('NOVA_STATE_DIR', '/data'))
    os.execvp('uvicorn', ['uvicorn', 'nova_server.app:app', '--host', '0.0.0.0',
                         '--port', '8787', '--no-proxy-headers'])
