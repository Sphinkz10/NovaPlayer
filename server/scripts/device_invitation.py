"""Export public laboratory trust material. Transfer its SHA-256 over a trusted channel.

This file is not signed, does not authorize a device, and contains no session or
private key. Owner approval through Control is still required for every device.
"""
import argparse
import hashlib
import ipaddress
import json
import re
import sqlite3
import ssl
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def export(state, origin, certificate, output, *, now=None):
    now = int(time.time() if now is None else now)
    url = urlsplit(origin)
    if (url.scheme != 'https' or url.username is not None or url.password is not None or
            url.path or url.query or url.fragment or url.port is None or not 1 <= url.port <= 65535):
        raise ValueError('Requer origem HTTPS IPv4 privada com porta explícita, sem caminho ou credenciais.')
    address = ipaddress.IPv4Address(url.hostname)
    allowed = ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','100.64.0.0/10','127.0.0.1/32')
    if not any(address in ipaddress.IPv4Network(network) for network in allowed):
        raise ValueError('Apenas um destino privado ou loopback de laboratório.')
    if origin != f'https://{address}:{url.port}':
        raise ValueError('Origem não canónica.')
    path = Path(state).resolve(strict=True)/'nova.sqlite3'
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
        if db.execute('SELECT COUNT(*) FROM admin WHERE id=1').fetchone()[0] != 1:
            raise ValueError('Criar primeiro o proprietário.')
        server_id = db.execute('SELECT server_id FROM server_identity WHERE id=1').fetchone()[0]
    if str(uuid.UUID(server_id)) != server_id:
        raise ValueError('Identidade inválida.')
    cert_path = Path(certificate)
    if cert_path.stat().st_size > 12000:
        raise ValueError('Certificado demasiado grande.')
    pem = cert_path.read_text(encoding='ascii')
    if not re.fullmatch(r'-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*', pem):
        raise ValueError('Fornecer apenas um certificado público PEM, nunca uma chave privada.')
    der = ssl.PEM_cert_to_DER_cert(pem.strip())
    if not 128 <= len(der) <= 8192:
        raise ValueError('Certificado inválido.')
    payload = {'version':1,'purpose':'nova-device-bootstrap','server_id':server_id,
               'client_origin':origin,'certificate_pem':pem,'expires_at':now+86400}
    raw = (json.dumps(payload, ensure_ascii=True, indent=2)+'\n').encode('utf8')
    with Path(output).open('xb') as target:
        target.write(raw)
    return {'created':True,'sha256':hashlib.sha256(raw).hexdigest(),'expires_at':payload['expires_at'],
            'requires_owner_approval':True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--certificate', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.state,args.origin,args.certificate,args.output)))
