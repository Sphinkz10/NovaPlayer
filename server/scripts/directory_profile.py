"""Export public Android bootstrap after pinned TLS 1.3 validation. No account password."""
import argparse
import json
import os
from pathlib import Path
import socket
import ssl
import sys
from urllib.parse import urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nova_directory.client import DirectoryClient
from nova_directory.protocol import private_origin


def export(origin,certificate,output):
    origin=private_origin(origin);path=Path(certificate)
    if path.stat().st_size>6000:raise ValueError('Certificate too large')
    pem=path.read_text(encoding='ascii')
    if pem.count('-----BEGIN CERTIFICATE-----')!=1 or 'PRIVATE KEY' in pem:raise ValueError('Public leaf certificate required')
    expected=ssl.PEM_cert_to_DER_cert(pem);address=urlsplit(origin)
    context=ssl.create_default_context(cafile=str(path));context.minimum_version=ssl.TLSVersion.TLSv1_3
    with socket.create_connection((address.hostname,address.port),timeout=5) as raw:
        with context.wrap_socket(raw,server_hostname=address.hostname) as secured:
            if secured.getpeercert(binary_form=True)!=expected:raise ValueError('Leaf certificate mismatch')
    client=DirectoryClient(origin,path)
    try:public=client.issuer()
    finally:client.close()
    profile={'version':1,'purpose':'nova-directory-bootstrap','origin':origin,'certificate_pem':pem,'public_key':public}
    raw=(json.dumps(profile,ensure_ascii=True,indent=2)+'\n').encode('ascii')
    if len(raw)>16384:raise ValueError('Profile too large')
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o644)
    with os.fdopen(fd,'wb') as file:file.write(raw)
    return {'public_profile':True,'passwords':False,'private_keys':False,'origin':origin}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',required=True);parser.add_argument('--certificate',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try:print(json.dumps(export(args.origin,args.certificate,args.output)))
    except (OSError,ValueError):raise SystemExit('Exportação recusada. Verifica a origem, o certificado público e o destino novo.') from None
