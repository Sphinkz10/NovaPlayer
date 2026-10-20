"""Validate and recover an offline LAN identity without generating new trust keys."""
import hashlib
import ipaddress
import json
import sqlite3
import time
from datetime import datetime,timezone
from contextlib import closing
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID

from nova_directory.identity import issuer_key
from nova_directory.client import server_identity
from nova_directory.protocol import encode,verify_record
from nova_server.lan import load,origin
from scripts.lan_install import render_lan

IDENTITY_FILES={
    'admin':{'server.key','server.crt','deployment.json','lan-ca.crt','client.crt','directory.crt'},
    'client':{'server.key','server.crt','deployment.json'},
    'directory':{'server.key','server.crt','deployment.json','nova-directory.json'}}
DIRECTORY_TABLES={'accounts','sessions','limits','entries','members','challenges','identity_metadata','registration_agents'}


def read_json(path,maximum=16384):
    if path.stat().st_size>maximum:raise ValueError('Metadados LAN demasiado grandes.')
    return json.loads(path.read_text(encoding='utf8'))


def certificate(path):
    if path.stat().st_size>8192:raise ValueError('Certificado LAN inválido.')
    return x509.load_pem_x509_certificate(path.read_bytes())


def der(cert):return cert.public_bytes(serialization.Encoding.DER)


def validate_lan(state):
    """Check offline consistency, including expired certificates, without migrations."""
    state=Path(state);identity=state/'identity'
    expected={role+'/'+name for role,names in IDENTITY_FILES.items() for name in names}
    if {p.relative_to(identity).as_posix() for p in identity.rglob('*') if p.is_file()}!=expected:
        raise ValueError('Identidade LAN incompleta ou com ficheiros desconhecidos.')
    config=load(identity/'admin/deployment.json')
    with closing(sqlite3.connect(state/'nova/nova.sqlite3')) as db,db:
        if db.execute('PRAGMA user_version').fetchone()[0]!=3:raise ValueError('Schema NOVA LAN não suportado.')
        if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
            raise ValueError('Código SQLite não permitido no estado NOVA.')
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='secret_metadata'").fetchone():
            pinned=db.execute('SELECT digest FROM secret_metadata WHERE id=1').fetchone()
            if pinned:
                vault=state/'nova/member-secrets.key'
                if not vault.is_file() or vault.stat().st_size!=32 or hashlib.sha256(vault.read_bytes()).hexdigest()!=pinned[0]:
                    raise ValueError('Chave de credenciais em falta ou diferente.')
    for role in IDENTITY_FILES:
        if load(identity/role/'deployment.json')!=config:raise ValueError('Configurações LAN diferentes.')
    ca=certificate(identity/'admin/lan-ca.crt')
    if not isinstance(ca.public_key(),ec.EllipticCurvePublicKey) or not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise ValueError('CA LAN inválida.')
    ca.verify_directly_issued_by(ca)
    certificates={}
    for role in IDENTITY_FILES:
        cert=certificate(identity/role/'server.crt');cert.verify_directly_issued_by(ca)
        key_path=identity/role/'server.key'
        if key_path.stat().st_size>4096:raise ValueError('Chave TLS inválida.')
        key=serialization.load_pem_private_key(key_path.read_bytes(),password=None)
        if not isinstance(key,ec.EllipticCurvePrivateKey) or key.public_key().public_numbers()!=cert.public_key().public_numbers():
            raise ValueError('Chave TLS não corresponde ao certificado.')
        if cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError('Certificado de serviço não pode ser CA.')
        if ExtendedKeyUsageOID.SERVER_AUTH not in cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value:
            raise ValueError('Finalidade TLS inválida.')
        names=cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if names.get_values_for_type(x509.IPAddress)!=[ipaddress.ip_address(config['ip'])]:
            raise ValueError('IP do certificado LAN diferente.')
        certificates[role]=cert
    if len({der(c) for c in certificates.values()})!=3:raise ValueError('Certificados de serviço repetidos.')
    for role in ('client','directory'):
        if der(certificate(identity/'admin'/(role+'.crt')))!=der(certificates[role]):
            raise ValueError('Confiança do Control diferente do serviço.')
    database=state/'directory/directory.sqlite3'
    allowed={'directory.sqlite3','directory.sqlite3-wal','directory.sqlite3-shm','directory-identity.key'}
    if (not database.is_file() or not (state/'directory/directory-identity.key').is_file() or
        any(p.relative_to(state/'directory').as_posix() not in allowed for p in (state/'directory').rglob('*') if p.is_file())):
        raise ValueError('Estado Directory incompleto ou com ficheiros desconhecidos.')
    with closing(sqlite3.connect(database)) as db,db:
        if db.execute('PRAGMA integrity_check').fetchone()!=('ok',) or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Base Directory inválida.')
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if db.execute('PRAGMA user_version').fetchone()[0]!=1 or tables!=DIRECTORY_TABLES:
            raise ValueError('Schema Directory não suportado para restauro seguro.')
        if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
            raise ValueError('Código SQLite não permitido no Directory.')
        expected_public=db.execute('SELECT public_key FROM identity_metadata WHERE id=1').fetchone()[0]
        if not isinstance(expected_public,str) or len(expected_public)!=43:raise ValueError('Emissor Directory em falta.')
        if not db.execute('SELECT 1 FROM accounts WHERE id=? AND disabled=0',(config['operator_id'],)).fetchone():
            raise ValueError('Proprietário Directory em falta ou desativado.')
        for entry,owner,server,public,version,raw in db.execute('SELECT id,owner_id,server_id,public_key,version,record FROM entries'):
            record=json.loads(raw);p=record['payload']
            descriptor=verify_record(record,origin(config,'directory'),now=p['issued_at'],expected_key=public)
            if (entry,owner,server,version)!=(p['entry_id'],p['owner_id'],descriptor.server_id,p['version']):
                raise ValueError('Registo Directory inconsistente.')
    # issuer_key refuses regeneration when the metadata already pins a public key.
    _,public=issuer_key(state/'directory',expected_public)
    profile=read_json(identity/'directory/nova-directory.json')
    if (set(profile)!={'version','purpose','origin','certificate_pem','public_key'} or profile['version']!=1 or
        profile['purpose']!='nova-directory-bootstrap' or profile['origin']!=origin(config,'directory') or
        profile['public_key']!=public or der(x509.load_pem_x509_certificate(profile['certificate_pem'].encode()))!=der(certificates['directory'])):
        raise ValueError('Bootstrap Directory não corresponde à identidade.')
    sid,signing=server_identity(state/'nova')
    control=state/'nova/directory-control.sqlite3'
    if control.is_file():
        with closing(sqlite3.connect(control)) as db,db:
            if db.execute('PRAGMA integrity_check').fetchone()!=('ok',) or db.execute('PRAGMA user_version').fetchone()[0]!=1:
                raise ValueError('Base Control Directory inválida.')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
                raise ValueError('Código SQLite não permitido no Control.')
            row=db.execute('SELECT origin,account,issuer_public,record FROM publication WHERE id=1').fetchone()
        if not row or row[0]!=origin(config,'directory'):raise ValueError('Origem Directory do Control diferente.')
        if row[1] and row[1]!=config['operator_id']:raise ValueError('Conta de publicação diferente do proprietário.')
        if row[2] and row[2]!=public:raise ValueError('Emissor Directory do Control diferente.')
        if row[3]:
            record=json.loads(row[3]);descriptor=verify_record(record,row[0],now=record['payload']['issued_at'],
                expected_key=encode(signing.public_key().public_bytes_raw()))
            if (descriptor.server_id!=sid or descriptor.client_origin!=origin(config,'client') or
                    der(x509.load_pem_x509_certificate(descriptor.certificate_pem.encode()))!=der(certificates['client'])):
                raise ValueError('Publicação não corresponde à identidade NOVA.')
    now=datetime.now(timezone.utc)
    return {'config':config,'server_id':sid,'directory_public_key':public,
        'fingerprint':hashlib.sha256(der(certificates['directory'])).hexdigest(),
        'tls_rotation_required':any(not c.not_valid_before_utc<=now<c.not_valid_after_utc for c in [ca,*certificates.values()])}


def deployment_values(state,text):
    """Only accept the generator's exact restricted YAML/JSON, never arbitrary commands."""
    if not isinstance(text,str) or len(text.encode('utf8'))>1024*1024:raise ValueError('Deployment inválido.')
    raw=json.loads(text);config=load(state/'identity/admin/deployment.json')
    services=raw['services'];admin=services['nova-admin'];jf=services['jellyfin']
    user,group=admin['user'].split(':');root=admin['volumes'][0]['source']
    if not root.endswith('/nova'):raise ValueError('Dataset NOVA inválido.')
    media={mount['target']:mount['source'] for mount in jf['volumes']}
    values={'state_root':root[:-5],'media_a':media['/media/source-a'],'media_b':media['/media/source-b'],
            'uid':int(user),'gid':int(group),'image':admin['image']}
    if raw!=render_lan(config,**values):raise ValueError('Deployment difere do perfil LAN suportado.')
    return values


def revoke_lan(state,*,now=None):
    """Retain accounts/shares as configuration, revoke capabilities and require republication."""
    moment=int(time.time() if now is None else now)
    with closing(sqlite3.connect(state/'directory/directory.sqlite3')) as db,db:
        for table in ('sessions','challenges','registration_agents','limits'):db.execute('DELETE FROM '+table)
        db.execute('UPDATE entries SET expires_at=0')
    with closing(sqlite3.connect(state/'nova/nova.sqlite3')) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS identity_recovery_barrier(id INTEGER PRIMARY KEY CHECK(id=1),not_before INTEGER NOT NULL)')
        previous=db.execute('SELECT not_before FROM identity_recovery_barrier WHERE id=1').fetchone()
        db.execute('INSERT OR REPLACE INTO identity_recovery_barrier VALUES(1,?)',(max(moment,previous[0] if previous else 0),))
    control=state/'nova/directory-control.sqlite3'
    if control.is_file():
        with closing(sqlite3.connect(control)) as db,db:
            db.execute("UPDATE publication SET renewal_credential=NULL,renewal_expires_at=NULL,checked_at=NULL,observation='recovery_republish_required'")


def write_restored_guidance(staging,manifest,*,state_root,image):
    state=staging/'state';identity=validate_lan(state)
    values=deployment_values(state,manifest['deployment'])
    values.update(state_root=state_root,image=image)
    rendered=render_lan(identity['config'],**values)
    def write(name,value):
        path=staging/name;path.write_text(value,encoding='utf8');path.chmod(0o600)
    write('instalar-no-truenas.yaml',json.dumps(rendered,indent=2)+'\n')
    write('NOVA-LAN-CA.crt',(state/'identity/admin/lan-ca.crt').read_text(encoding='ascii'))
    report={**{k:v for k,v in identity.items() if k!='config'},'state_root':state_root,'image':image,
        'control':origin(identity['config'],'admin'),'directory':origin(identity['config'],'directory'),
        'requires_republication':True,'media_grants_revoked':True,'directory_accounts_and_shares':'snapshot configuration retained; review before republication'}
    write('RECUPERACAO.json',json.dumps(report,indent=2)+'\n')
    write('ABRIR_RESTAURO.md',f'''# NOVA LAN — restauro numa instalação nova

O restauro preservou as identidades NOVA/Directory e os três certificados. Não geres outra instalação com o assistente: isso criaria identidades diferentes.

1. Manter os quatro serviços antigos parados. Preparar um dataset NOVO e vazio em `{state_root}`; copiar apenas o conteúdo de `state/` e confirmar UID/GID {values['uid']}:{values['gid']} e permissões privadas. A ferramenta não acede ao NAS nem copia ficheiros para ele.
2. Rever as contas e partilhas recuperadas da data da cópia. Revogações posteriores à cópia não podem ser deduzidas desse snapshot. Todas as permissões de media, dispositivos e sessões foram invalidadas.
3. Nas Apps, usar `instalar-no-truenas.yaml`, regenerado pelo perfil seguro com a imagem indicada no comando de restauro. `deployment.original.txt` é apenas um registo e não é executado.
4. Abrir {report['control']} e entrar novamente. Confirmar IP, relógio e CA. O certificado público NOVA-LAN-CA.crt recuperado é o mesmo. Necessidade de rotação TLS: {report['tls_rotation_required']}.
5. No Control, verificar a configuração/indexação Jellyfin com o administrador existente; depois publicar novamente no Directory com a conta proprietária. A renovação automática antiga foi removida.
6. Na TV, manter a configuração de confiança existente, entrar novamente no Directory e associar de novo. No Control, voltar a atribuir bibliotecas e aprovar cada dispositivo.

Directory: {report['directory']}
Fingerprint: {report['fingerprint']}

Certificados expirados são preservados para recuperação, mas o runtime continua a recusar a ligação até uma rotação autorizada. A chave privada da CA offline e a chave privada age não pertencem a este estado recuperado. Media e cache não estão na cópia. Não iniciar em simultâneo duas instâncias com esta identidade/IP. Aceitação física TrueNAS/TV continua por executar.
''')
    return report
