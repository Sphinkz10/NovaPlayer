"""Prepare a NEW TrueNAS LAN installation on the owner's PC, without SSH or Docker."""
import argparse
from datetime import datetime,timedelta,timezone
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
from nova_server.lan import lan_ip,origin,validate
from nova_server.storage import Store
from nova_server.security import hash_password
from nova_directory.store import Registry
from nova_directory.client import server_identity
from scripts.truenas import render as legacy_render


def write(path,data,mode=0o600):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
    with os.fdopen(fd,'wb') as file:file.write(data)


def pem_key(key):
    return key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())


def prepare(output,*,ip,state_root,media_a,media_b,uid,gid,image,version,username,password,ports=None):
    ip=lan_ip(ip)
    # Reuse the established dataset, version, image and non-root validation before writing anything.
    config=legacy_render(state_root,media_a,media_b,uid,gid,image,version)
    if not re.fullmatch(r'[a-z][a-z0-9_.-]{2,39}',username):raise ValueError('Conta com 3–40 caracteres minúsculos.')
    hashed=hash_password(password)
    ports=ports or {'admin':9444,'client':8920,'directory':9443}
    validate({'version':1,'ip':ip,'ports':ports,'operator_id':'00000000-0000-4000-8000-000000000001'})
    output=Path(output);output.mkdir(mode=0o700) # Never reuse or overwrite an existing deployment.
    nas=output/'copiar-para-nas';nas.mkdir(mode=0o700)
    for name in ('nova','directory','identity','jellyfin/config','jellyfin/cache'):(nas/name).mkdir(mode=0o700,parents=True)
    for role in ports:(nas/'identity'/role).mkdir(mode=0o700)
    store=Store(nas/'nova');store.bootstrap(username,hashed)
    registry=Registry(nas/'directory',f'https://{ip}:{ports["directory"]}')
    operator=registry.create_account(username,password)
    server_identity(store.dir,create_key=True)
    deployment=validate({'version':1,'ip':ip,'ports':ports,'operator_id':operator})
    now=datetime.now(timezone.utc);ca_key=ec.generate_private_key(ec.SECP256R1())
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'NOVA LAN · instalação privada')])
    ca=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),critical=False)
        .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),critical=True)
        .sign(ca_key,hashes.SHA256()))
    ca_pem=ca.public_bytes(serialization.Encoding.PEM)
    write(output/'NOVA-LAN-CA.crt',ca_pem,0o644)
    write(output/'GUARDAR-OFFLINE-ca.key',pem_key(ca_key)) # Signing key is never mounted in containers.
    leaves={}
    for role in ports:
        folder=nas/'identity'/role;key=ec.generate_private_key(ec.SECP256R1())
        leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'NOVA '+role)]))
            .issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]),critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
            .add_extension(x509.KeyUsage(True,False,False,False,False,False,False,False,False),critical=True)
            .sign(ca_key,hashes.SHA256()))
        leaves[role]=leaf;write(folder/'server.key',pem_key(key));write(folder/'server.crt',leaf.public_bytes(serialization.Encoding.PEM),0o644)
        write(folder/'deployment.json',(json.dumps(deployment)+'\n').encode())
    admin=nas/'identity/admin'
    write(admin/'lan-ca.crt',ca_pem,0o644)
    write(admin/'client.crt',leaves['client'].public_bytes(serialization.Encoding.PEM),0o644)
    write(admin/'directory.crt',leaves['directory'].public_bytes(serialization.Encoding.PEM),0o644)
    profile={'version':1,'purpose':'nova-directory-bootstrap','origin':origin(deployment,'directory'),
             'certificate_pem':leaves['directory'].public_bytes(serialization.Encoding.PEM).decode(),'public_key':registry.identity_public}
    write(nas/'identity/directory/nova-directory.json',(json.dumps(profile)+'\n').encode(),0o644)

    def mount(source,target,ro=False):
        return {'type':'bind','source':source,'target':target,'read_only':ro,'bind':{'create_host_path':False}}
    # Jellyfin stays unexposed: only NOVA administration/media may call it on the internal network.
    jf=config['services']['jellyfin'];jf.pop('ports',None)
    config['services']={'jellyfin':jf}
    for role in ports:
        service={'image':image,'user':f'{uid}:{gid}','restart':'unless-stopped','read_only':True,
            'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'tmpfs':['/tmp:rw,noexec,nosuid,size=16m'],
            'command':['python','-m','nova_server.lan_launch',role],
            'environment':{'NOVA_JELLYFIN_URL':'http://jellyfin:8096','NOVA_STATE_DIR':'/data'},
            'ports':[f'{ip}:{ports[role]}:{ports[role]}/tcp'],
            'volumes':[mount(state_root+('/directory' if role=='directory' else '/nova'),'/data'),
                       mount(state_root+'/identity/'+role,'/identity',True)],
            'networks':['nova_internal'],
            'healthcheck':{'test':['CMD','python','-c',
                "import socket; s=socket.create_connection(('127.0.0.1',"+str(ports[role])+"),3); s.close()"],
                'interval':'20s','timeout':'5s','start_period':'20s','retries':3}}
        if role!='directory':service['depends_on']=['jellyfin','nova-directory']
        config['services']['nova-'+role]=service
    write(output/'instalar-no-truenas.yaml',(json.dumps(config,ensure_ascii=False,indent=2)+'\n').encode(),0o644)
    fingerprint=hashlib.sha256(leaves['directory'].public_bytes(serialization.Encoding.DER)).hexdigest()
    info={'version':1,'nas_ip':ip,'state_root':state_root,'uid':uid,'gid':gid,'image':image,
          'control':origin(deployment,'admin'),'tv_directory':origin(deployment,'directory'),
          'tv_fingerprint':fingerprint,'client':origin(deployment,'client'),'owner':username}
    write(output/'INSTALACAO.json',(json.dumps(info,indent=2)+'\n').encode(),0o644)
    guide=f'''# NOVA LAN — começar aqui

1. No TrueNAS de teste, preparar os datasets e ACL das origens e de `{state_root}`. Copiar apenas o CONTEÚDO de `copiar-para-nas` para esse diretório, preservando os ficheiros privados e atribuindo propriedade ao UID/GID {uid}:{gid}. Não copiar a chave GUARDAR-OFFLINE para o NAS ou para a TV. Não substituir estado de outra instalação.
2. Apps → Discover → Install via YAML: colar `instalar-no-truenas.yaml`. A imagem está fixada por digest. São publicados apenas três endpoints HTTPS no IP privado {ip}; Jellyfin não tem porta publicada.
3. No PC do proprietário, importar o certificado público `NOVA-LAN-CA.crt` como CA de confiança do utilizador/navegador. Abrir {info['control']} e entrar com a conta {username} e a palavra-passe escolhida. Não ignorar um erro TLS; verificar primeiro IP, relógio e CA.
4. No Control, configurar Jellyfin/bibliotecas, inicializar/publicar o Directory com a conta {username}. A palavra-passe inicial do Directory é a escolhida no instalador. A publicação será renovada automaticamente com a credencial limitada existente. Na secção Ligar uma TV, podes criar uma conta de familiar antes da associação; ainda tens de lhe atribuir bibliotecas e aprovar a TV.
5. Na APK NOVA, escolher Configurar nesta TV. Directory: {info['tv_directory']}
   Impressão digital TLS: {fingerprint}
   Comparar todos os caracteres com este ficheiro do proprietário. Não é necessária uma ligação ADB.
6. Entrar com a conta Directory na TV, consultar o código no Control, aplicar bibliotecas e aprovar. Abrir NOVA Cinema para reproduzir.

Usar IP reservado no DHCP. A alteração de IP ou perda de identidade exige migração de confiança, não editar os ficheiros em funcionamento. Este gerador cria apenas instalações NOVAS. A chave offline e a pasta privada devem ficar guardadas em local privado; a recuperação M2 antiga não inclui todo este estado Directory/TLS. Aceitação física e backup/restauro completo deste perfil LAN continuam por validar.

TrueNAS 24.10+ com Apps Docker; verificar versão concreta antes de instalar. Estes resultados não certificam o teu NAS nem os codecs das boxes. WireGuard/Tailscale/NetBird e SEC-01…12 mantêm os gates próprios.
'''
    write(output/'ABRIR_PRIMEIRO.md',guide.encode(),0o600)
    return info


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    images=parser.add_mutually_exclusive_group(required=True)
    images.add_argument('--image');images.add_argument('--image-file')
    args=parser.parse_args()
    values={name:input(label).strip() for name,label in (
        ('ip','IP privado reservado do NAS: '),('version','Versão TrueNAS: '),('state_root','Dataset de estado (/mnt/POOL/nova): '),
        ('media_a','Origem A (/mnt/POOL/media-a): '),('media_b','Origem B (/mnt/POOL/media-b): '),
        ('uid','UID da conta de serviço: '),('gid','GID da conta de serviço: '),('username','Nome do proprietário (minúsculas): '))}
    password=getpass.getpass('Palavra-passe inicial NOVA/Directory (14+ caracteres): ')
    if password!=getpass.getpass('Confirmar palavra-passe: '):raise ValueError('As palavras-passe não coincidem.')
    values['uid']=int(values['uid']);values['gid']=int(values['gid'])
    image=args.image or Path(args.image_file).read_text(encoding='ascii').strip()
    prepare(args.output,image=image,password=password,**values)
    print('Pacote criado. Abrir ABRIR_PRIMEIRO.md dentro da pasta escolhida. Nenhum NAS foi alterado.')


if __name__=='__main__':main()
