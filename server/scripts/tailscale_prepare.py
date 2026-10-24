"""Offline commissioning of a Tailscale profile, BEFORE Directory/TV association.

Uses the existing offline CA and client TLS key. Produces a NEW staging folder;
does not edit the installation, enroll a tailnet peer or configure a NAS network.
"""
import argparse
from contextlib import closing
from datetime import datetime,timedelta,timezone
import hashlib
import ipaddress
import json
import os
import re
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from nova_server.gateway_channel import canonical,read_private
from nova_server.lan import load,origin
from nova_server.tailscale_profile import control_origin,gateway_origin,TailscaleProfiles
from scripts.lan_install import write


def environment(compose,base_origin):
    for role in ('admin','client'):
        compose['services']['nova-'+role]['environment'].update({
            'NOVA_TAILSCALE_MANAGED':'1','NOVA_TAILSCALE_PUBLIC_CONFIG':'/identity/tailscale-public.json',
            'NOVA_TAILSCALE_BASE_ORIGIN':base_origin,
            'NOVA_TAILSCALE_CERTIFICATE_FILE':'/identity/client.crt' if role=='admin' else '/identity/server.crt'})
    return compose


def prepare(installation,output,*,gateway,image,control='https://controlplane.tailscale.com'):
    installation=Path(installation).resolve(strict=True);state=installation/'copiar-para-nas'
    output=Path(output).resolve()
    if output==installation or installation in output.parents:
        raise ValueError('Use a separate new staging folder, outside the installation')
    if not isinstance(image,str) or not re.fullmatch(r'ghcr\.io/sphinkz10/nova-core@sha256:[a-f0-9]{64}',image):
        raise ValueError('Tested NOVA Core image pinned by digest required')
    control=control_origin(control)
    config=load(state/'identity/client/deployment.json');base=origin(config,'client')
    remote=gateway_origin(f'https://{gateway}:{config["ports"]["client"]}')
    # Inspect offline state without creating/migrating a database or identity.
    database=state/'nova/nova.sqlite3'
    if not database.is_file():raise ValueError('Prepared installation required')
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
        server=db.execute('SELECT server_id FROM server_identity WHERE id=1').fetchone()[0]
        if db.execute('SELECT 1 FROM devices LIMIT 1').fetchone():
            raise ValueError('Prepare Tailscale before associating any TV')
    if (state/'nova/directory-control.sqlite3').exists():
        raise ValueError('Prepare Tailscale before publishing the Directory identity')
    if (state/'identity/client/tailscale-public.json').exists():
        raise ValueError('Tailscale profile already prepared; do not silently replace trust')
    ca=x509.load_pem_x509_certificate((installation/'NOVA-LAN-CA.crt').read_bytes())
    ca_key=serialization.load_pem_private_key(read_private(installation/'GUARDAR-OFFLINE-ca.key',8192),password=None)
    leaf=x509.load_pem_x509_certificate((state/'identity/client/server.crt').read_bytes())
    key=serialization.load_pem_private_key(read_private(state/'identity/client/server.key',8192),password=None)
    if (not isinstance(ca_key,ec.EllipticCurvePrivateKey) or not isinstance(key,ec.EllipticCurvePrivateKey) or
            ca_key.public_key().public_numbers()!=ca.public_key().public_numbers() or
            key.public_key().public_numbers()!=leaf.public_key().public_numbers() or
            not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca or
            leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca):
        raise ValueError('Original offline CA and client key required')
    ca.verify_directly_issued_by(ca);leaf.verify_directly_issued_by(ca)
    now=datetime.now(timezone.utc)
    if not ca.not_valid_before_utc<=now<ca.not_valid_after_utc or not leaf.not_valid_before_utc<=now<leaf.not_valid_after_utc:
        raise ValueError('Valid original certificates required')
    names=leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    if names.get_values_for_type(x509.IPAddress)!=[ipaddress.ip_address(config['ip'])]:
        raise ValueError('Use a fresh LAN installation, without another remote provider')
    builder=(x509.CertificateBuilder().subject_name(leaf.subject).issuer_name(leaf.issuer)
        .public_key(leaf.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(max(leaf.not_valid_before_utc,now-timedelta(minutes=5)))
        .not_valid_after(min(leaf.not_valid_after_utc,ca.not_valid_after_utc)))
    for extension in leaf.extensions:
        value=x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(config['ip'])),
            x509.IPAddress(ipaddress.ip_address(gateway))]) if isinstance(extension.value,x509.SubjectAlternativeName) else extension.value
        builder=builder.add_extension(value,critical=extension.critical)
    prepared=builder.sign(ca_key,hashes.SHA256())
    public=prepared.public_bytes(serialization.Encoding.PEM)
    policy={'schema_version':1,'server_id':server,'revision':1,'control_origin':control,'client_origin':remote}
    compose=json.loads((installation/'instalar-no-truenas.yaml').read_text(encoding='utf8'))
    from scripts.lan_recovery import deployment_values,validate_lan
    if validate_lan(state)['tls_rotation_required']:raise ValueError('Original LAN certificates require renewal')
    # Refuse user-edited services, commands or new mounts in the input deployment.
    deployment_values(state,json.dumps(compose))
    environment(compose,base)
    for role in ('admin','client','directory'):compose['services']['nova-'+role]['image']=image
    output.mkdir(mode=0o700)
    for role in ('admin','client'):(output/'copiar-para-nas/identity'/role).mkdir(parents=True,mode=0o700)
    write(output/'copiar-para-nas/identity/client/server.crt',public,0o644)
    write(output/'copiar-para-nas/identity/admin/client.crt',public,0o644)
    for role in ('admin','client'):write(output/'copiar-para-nas/identity'/role/'tailscale-public.json',canonical(policy))
    write(output/'instalar-no-truenas.yaml',(json.dumps(compose,indent=2)+'\n').encode())
    report={'schema_version':1,'server_id':server,'base_origin':base,'client_origin':remote,
        'control_origin':control,'image':image,'certificate_sha256':hashlib.sha256(prepared.public_bytes(serialization.Encoding.DER)).hexdigest(),
        'client_key_preserved':True,'offline_ca_preserved':True,'gateway_installed':False,'owner_approval_required':True}
    write(output/'PERFIL_TAILSCALE.json',canonical(report),0o644)
    write(output/'ABRIR_PRIMEIRO.md',f'''# Perfil Tailscale — preparação offline

Esta pasta é uma atualização de preparação da instalação NOVA original, antes da publicação Directory e da associação de TVs. Não instala nem inscreve o peer Tailscale. O IP {gateway} deve pertencer ao peer do NOVA Server, num namespace dedicado ao serviço; não expor a administração do NAS ao tailnet.

1. Com os serviços parados, copiar os quatro ficheiros de `copiar-para-nas/identity` para os destinos correspondentes da instalação preparada, preservando permissões. Substituem apenas o certificado público do cliente e a cópia pública no Control; as chaves privadas e a CA são as originais.
2. Usar o YAML desta pasta e arrancar novamente os serviços com a imagem NOVA Core desta revisão, fixada por digest. Uma imagem 0.12 anterior não implementa a aprovação deste perfil. Não adicionar portas de administração, redes do host ou socket Docker. A instalação automática do gateway Tailscale e o encaminhamento até ao NOVA cliente continuam por implementar nesta entrega.
3. No Control, atualizar o perfil Tailscale. Comparar coordenador `{control}`, origem `{remote}` e SHA-256 `{report['certificate_sha256']}`. Aprovar o perfil para as TVs apenas depois de o peer e o acesso HTTPS NOVA terem sido preparados.
4. Publicar o Directory e associar a TV depois de reiniciar com o novo certificado. A APK 0.12 distribuída continua LAN/WireGuard; o adaptador Tailscale ainda usa a variante de laboratório.

Desativar o perfil no Control bloqueia a API NOVA pelo endereço Tailscale, incluindo transferências em curso; não remove o peer do tailnet. O funcionamento do túnel e a inscrição são verificações separadas. Nunca copiar GUARDAR-OFFLINE-ca.key para o NAS/TV. Este preparador não altera o original nem prolonga a validade do certificado. Guardar esta pasta e o original em privado; a cópia cifrada deve usar as ferramentas atualizadas desta revisão.
'''.encode('utf8'))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--gateway',required=True);parser.add_argument('--image',required=True)
    parser.add_argument('--control',default='https://controlplane.tailscale.com')
    args=parser.parse_args()
    prepare(args.installation,args.output,gateway=args.gateway,control=args.control,image=args.image)
    print('Perfil preparado numa pasta nova. Ler ABRIR_PRIMEIRO.md. Nenhum NAS foi alterado.')
