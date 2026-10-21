"""Prepare a NEW LAN + native WireGuard installation, without changing a NAS.

WireGuard's encrypted UDP transport needs a reachable endpoint. No HTTP or NAS
management port is published on the Internet. CGNAT needs a separate relay or
overlay provider; this installer does not promise NAT traversal.
"""
import argparse
import base64
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization
from nova_server.gateway_channel import canonical
from nova_server.wireguard_gateway import GatewayPolicy
from nova_server.storage import Store
from scripts.lan_install import prepare as prepare_lan, render_lan, write


def endpoint(value):
    # UDP address only, never a command/URL/config fragment. DNS is allowed for
    # the encrypted underlay; the inner HTTPS host remains an exact private IP.
    if not isinstance(value,str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,252}:[0-9]{1,5}',value):
        raise ValueError('Endpoint WireGuard: nome-ou-IPv4:porta UDP.')
    host,port=value.rsplit(':',1)
    if not 1<=int(port)<=65535 or str(int(port))!=port:
        raise ValueError('Porta UDP inválida.')
    if re.fullmatch(r'[0-9.]+',host):ipaddress.IPv4Address(host)
    elif any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in host.split('.')):
        raise ValueError('Nome DNS inválido.')
    return value


def render(deployment,*,state_root,media_a,media_b,uid,gid,image,version,gateway_image):
    if not re.fullmatch(r'ghcr\.io/sphinkz10/nova-gateway@sha256:[a-f0-9]{64}',gateway_image):
        raise ValueError('Imagem nova-gateway fixada por digest obrigatória.')
    compose=render_lan(deployment,state_root=state_root,media_a=media_a,media_b=media_b,
        uid=uid,gid=gid,image=image,version=version)
    state_root=state_root.rstrip('/')
    def mount(source,target,ro=True):
        return {'type':'bind','source':state_root+'/'+source,'target':target,'read_only':ro,'bind':{'create_host_path':False}}
    services=compose['services'];client=services['nova-client'];admin=services['nova-admin']
    services['nova-gateway']={
        'image':gateway_image,'user':'0:0','restart':'unless-stopped','read_only':True,
        'cap_drop':['ALL'],'cap_add':['NET_ADMIN','DAC_OVERRIDE','CHOWN'],
        'security_opt':['no-new-privileges:true'], 'pids_limit':64,
        'tmpfs':['/run/nova-gateway:rw,noexec,nosuid,size=1m,mode=0700','/tmp:rw,noexec,nosuid,size=4m'],
        'sysctls':{'net.ipv4.ip_forward':'0','net.ipv6.conf.all.forwarding':'0','net.ipv6.conf.all.disable_ipv6':'1'},
        'ports':client.pop('ports')+[f"{deployment['ip']}:51820:51820/udp"],
        'volumes':[mount('identity/gateway','/identity'),mount('gateway/channel','/channel',False),mount('gateway/leases','/leases',False)],
        'networks':['nova_internal']}
    client.pop('networks');client['network_mode']='service:nova-gateway'
    client['depends_on']={name:{'condition':'service_started'} for name in client['depends_on']}
    client['depends_on']['nova-gateway']={'condition':'service_healthy','restart':True}
    admin['environment'].update({'NOVA_WIREGUARD_CHANNEL_DIR':'/channel','NOVA_WIREGUARD_CHANNEL_KEY_FILE':'/identity/channel.key'})
    admin['volumes'].append(mount('gateway/channel','/channel',False))
    client['environment']['NOVA_WIREGUARD_PUBLIC_CONFIG']='/identity/wireguard-public.json'
    client['volumes'].append(mount('gateway/channel','/channel',True))
    return compose


def prepare(output,*,gateway_image,udp_endpoint,pool='10.222.0.0/24',gateway='10.222.0.1',**lan):
    endpoint(udp_endpoint)
    private=X25519PrivateKey.generate()
    public=base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode('ascii')
    GatewayPolicy('00000000-0000-4000-8000-000000000001',public,pool,gateway)
    if ipaddress.IPv4Address(lan['ip']) in ipaddress.IPv4Network(pool):
        raise ValueError('A rede WireGuard deve ser diferente da LAN do NAS.')
    # Validate every render input before creating an installation directory.
    provisional={'version':1,'ip':lan['ip'],'ports':{'admin':9444,'client':8920,'directory':9443},
        'operator_id':'00000000-0000-4000-8000-000000000001'}
    render(provisional,gateway_image=gateway_image,**{k:lan[k] for k in ('state_root','media_a','media_b','uid','gid','image','version')})
    info=prepare_lan(output,**lan,gateway_ip=gateway)
    output=Path(output);nas=output/'copiar-para-nas'
    for name in ('identity/gateway','gateway/channel','gateway/leases'):(nas/name).mkdir(mode=0o700,parents=True,exist_ok=True)
    with Store(nas/'nova')._db() as db:
        server_id=db.execute('SELECT server_id FROM server_identity WHERE id=1').fetchone()[0]
    deployment=json.loads((nas/'identity/client/deployment.json').read_text())
    policy={'server_id':server_id,'public_key':public,'pool':pool,'gateway':gateway}
    key=base64.b64encode(private.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()))+b'\n'
    write(nas/'identity/gateway/wireguard.key',key)
    secret=os.urandom(32)
    for role in ('gateway','admin','client'):write(nas/'identity'/role/'channel.key',secret)
    write(nas/'identity/gateway/gateway.json',canonical({'schema_version':1,'policy':policy,'client_port':deployment['ports']['client'],'listen_port':51820}))
    public_config=canonical({'schema_version':1,'policy':policy,'endpoint':udp_endpoint,
        'client_origin':f"https://{gateway}:{deployment['ports']['client']}"})
    write(output/'WIREGUARD_PUBLICO.json',public_config,0o644)
    write(nas/'identity/client/wireguard-public.json',public_config)
    compose=render(deployment,gateway_image=gateway_image,**{k:lan[k] for k in ('state_root','media_a','media_b','uid','gid','image','version')})
    # This file belongs to the fresh installation just created by this call.
    (output/'instalar-no-truenas.yaml').write_text(json.dumps(compose,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    write(output/'WIREGUARD.md',('''# Gateway WireGuard — instalação de teste

Seguir primeiro ABRIR_PRIMEIRO.md. A imagem adicional tem de corresponder ao código deste gerador.
O contentor nova-gateway possui a rede partilhada apenas com nova-client; a administração e o Directory usam outros contentores.
São publicadas a porta HTTPS LAN do cliente e UDP 51820 no IP privado do NAS. Para acesso externo direto, o proprietário tem de encaminhar apenas UDP para este endpoint; o gerador não configura o router nem ultrapassa CGNAT.
NET_ADMIN permite criar a interface e a firewall só nesta rede Docker. DAC_OVERRIDE/CHOWN permitem ler e escrever apenas os volumes privados montados, com propriedade da conta de serviço. Não se usa privileged, host network, SYS_ADMIN, socket Docker, mounts /proc do host ou módulos do kernel.
O kernel do NAS tem de disponibilizar WireGuard e nftables. A falta de suporte faz falhar o arranque. Não instalar pacotes no sistema base do TrueNAS.
Preservar os modos 0700 dos diretórios e 0600 das chaves, além do UID/GID indicado no guia LAN. Guardar toda a pasta em privado; a chave WireGuard não vai para as TVs.
Parar/atualizar a aplicação Compose completa: nova-client partilha a rede do gateway, pelo que não se deve substituir isoladamente esse contentor. Um reinício normal reconstrói a interface e preserva os endereços na base de leases.
Os endereços autorizados expiram na firewall do kernel em até 13 segundos sem renovação, incluindo tráfego TCP já estabelecido. A saída normal remove a interface. Uma morte abrupta pode deixar a interface no namespace retido pelo cliente, mas a firewall não conserva autorização indefinida.
Este pacote provisiona o gateway. A configuração da TV e a aceitação física têm validações próprias; não importar WIREGUARD_PUBLICO.json como convite de associação.
''').encode('utf-8'))
    return info


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);parser.add_argument('--image',required=True);parser.add_argument('--gateway-image',required=True)
    args=parser.parse_args()
    values={name:input(label).strip() for name,label in (
        ('ip','IP privado reservado do NAS: '),('version','Versão TrueNAS: '),('state_root','Dataset de estado (/mnt/POOL/nova): '),
        ('media_a','Origem A: '),('media_b','Origem B: '),('uid','UID: '),('gid','GID: '),('username','Proprietário: '),
        ('udp_endpoint','Endpoint UDP alcançável pela TV (nome:porta): '),('pool','Rede WireGuard (ex.: 10.222.0.0/24): '),
        ('gateway','IP WireGuard do servidor (ex.: 10.222.0.1): '))}
    password=getpass.getpass('Palavra-passe inicial (14+ caracteres): ')
    if password!=getpass.getpass('Confirmar palavra-passe: '):raise ValueError('As palavras-passe não coincidem.')
    values['uid']=int(values['uid']);values['gid']=int(values['gid'])
    prepare(args.output,image=args.image,gateway_image=args.gateway_image,password=password,**values)
    print('Pacote novo criado. Abrir ABRIR_PRIMEIRO.md e WIREGUARD.md. Nenhum NAS foi alterado.')


if __name__=='__main__':main()
