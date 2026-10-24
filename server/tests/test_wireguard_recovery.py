import base64
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile

import pytest

from scripts.wireguard_install import prepare
from scripts.lan_recovery import validate_lan,deployment_values,write_restored_guidance
from scripts.wireguard_recovery import revoke_gateway_runtime
from scripts.recovery import backup,restore,files_for_backup,extract_checked,revoke_restored_sessions
from nova_server.gateway_channel import GatewayChannel,atomic_private
from nova_server.storage import Store

IMAGE='ghcr.io/sphinkz10/nova-core@sha256:'+'a'*64
GATEWAY='ghcr.io/sphinkz10/nova-gateway@sha256:'+'b'*64


@pytest.fixture
def wg_state(tmp_path):
    bundle=tmp_path/'bundle'
    prepare(bundle,gateway_image=GATEWAY,udp_endpoint='vpn.example.org:51820',
        ip='192.168.50.20',state_root='/mnt/pool/nova',media_a='/mnt/pool/a',media_b='/mnt/pool/b',
        uid=10001,gid=10001,image=IMAGE,version='25.10.5',username='owner',password='recovery-fixture-password')
    state=bundle/'copiar-para-nas';data=state/'jellyfin/config/data';data.mkdir()
    with sqlite3.connect(data/'jellyfin.db') as db:
        db.executescript('CREATE TABLE Users(Id TEXT); INSERT INTO Users VALUES("owner");'
            'CREATE TABLE Devices(Id TEXT); INSERT INTO Devices VALUES("old-device");'
            'CREATE TABLE ApiKeys(Id TEXT); INSERT INTO ApiKeys VALUES("old-api-key");')
    return bundle,state


def test_gateway_snapshot_preserves_identity_but_excludes_volatile_authorizations(wg_state,tmp_path):
    bundle,state=wg_state
    identity=validate_lan(state,wireguard=True)
    with pytest.raises(ValueError):validate_lan(state)
    with pytest.raises(ValueError):deployment_values(state,(bundle/'instalar-no-truenas.yaml').read_text())
    channel=GatewayChannel(state/'gateway/channel',state/'identity/gateway/channel.key')
    channel.write('plan',{'old':'authorization'})
    (state/'gateway/leases/leases.sqlite3').write_bytes(b'volatile attribution')
    names={p.relative_to(state).as_posix() for p in files_for_backup(state)[1]}
    assert {'identity/gateway/wireguard.key','identity/client/wireguard-public.json'}<=names
    assert not any(n.startswith('gateway/') for n in names)
    staging=tmp_path/'staging';shutil.copytree(state,staging/'state',ignore=shutil.ignore_patterns('gateway'))
    # Copytree ignore also excluded identity/gateway, which is persistent identity.
    shutil.copytree(state/'identity/gateway',staging/'state/identity/gateway')
    target=staging/'state';old_secret=(target/'identity/admin/channel.key').read_bytes()
    report=write_restored_guidance(staging,{'deployment':(bundle/'instalar-no-truenas.yaml').read_text()},
        state_root='/mnt/pool/recovered',image=IMAGE,gateway_image=GATEWAY)
    revoke_restored_sessions(target);revoke_gateway_runtime(target)
    assert report['server_id']==identity['server_id'] and report['wireguard_reapproval_required']
    assert validate_lan(target,wireguard=True)['server_id']==identity['server_id']
    assert (target/'identity/gateway/wireguard.key').read_bytes()==(state/'identity/gateway/wireguard.key').read_bytes()
    assert (target/'identity/admin/channel.key').read_bytes()!=old_secret
    assert not list((target/'gateway/channel').iterdir()) and not list((target/'gateway/leases').iterdir())
    rendered=json.loads((staging/'instalar-no-truenas.yaml').read_text())
    assert len(rendered['services'])==5 and rendered['services']['nova-client']['network_mode']=='service:nova-gateway'
    assert rendered['services']['nova-gateway']['volumes'][0]['source']=='/mnt/pool/recovered/identity/gateway'


@pytest.mark.parametrize('change',['private_key','channel','policy','public_origin','image','privileged','extra_mount'])
def test_recovery_rejects_mismatched_identity_and_arbitrary_compose(wg_state,change):
    bundle,state=wg_state
    text=(bundle/'instalar-no-truenas.yaml').read_text();compose=json.loads(text)
    if change=='private_key':(state/'identity/gateway/wireguard.key').write_bytes(base64.b64encode(b'x'*32)+b'\n')
    elif change=='channel':(state/'identity/client/channel.key').write_bytes(b'x'*32)
    elif change in ('policy','public_origin'):
        path=state/'identity/client/wireguard-public.json';value=json.loads(path.read_text())
        if change=='policy':value['policy']['pool']='10.223.0.0/24'
        else:value['client_origin']='https://8.8.8.8:8920'
        path.write_text(json.dumps(value))
    elif change=='image':compose['services']['nova-gateway']['image']='latest'
    elif change=='privileged':compose['services']['nova-gateway']['privileged']=True
    else:compose['services']['nova-gateway']['volumes'].append({'source':'/','target':'/host'})
    with pytest.raises(ValueError):
        validate_lan(state,wireguard=True)
        deployment_values(state,json.dumps(compose),wireguard=True)


def test_archive_never_accepts_runtime_mailbox_or_lease_database(tmp_path):
    for name in ('state/gateway/channel/plan.json','state/gateway/leases/leases.sqlite3'):
        raw=io.BytesIO()
        with tarfile.open(fileobj=raw,mode='w') as archive:
            item=tarfile.TarInfo(name);archive.addfile(item,io.BytesIO())
        raw.seek(0)
        with pytest.raises(ValueError,match='fora'):extract_checked(raw,tmp_path)


def test_encrypted_wireguard_roundtrip_and_tamper_rejection(wg_state,tmp_path):
    age=os.environ.get('NOVA_TEST_AGE') or shutil.which('age')
    if not age:pytest.skip('age integration also runs in the disposable Docker gate')
    age=Path(age);keygen=age.with_name('age-keygen'+age.suffix)
    key=tmp_path/'recovery.key'
    subprocess.run([str(keygen),'-o',str(key)],check=True,capture_output=True)
    recipient=subprocess.check_output([str(keygen),'-y',str(key)],text=True).strip()
    bundle,state=wg_state;source={p:p.read_bytes() for p in state.joinpath('identity').rglob('*') if p.is_file()}
    channel=GatewayChannel(state/'gateway/channel',state/'identity/gateway/channel.key');channel.write('plan',{'old':'snapshot'})
    encrypted=tmp_path/'backup.age'
    report=backup(state,encrypted,recipient,deployment=bundle/'instalar-no-truenas.yaml',stopped=True,age=str(age))
    assert report['profile']=='wireguard' and report['format']==3
    with pytest.raises(ValueError,match='gateway-image'):
        restore(encrypted,tmp_path/'missing-image',key,age=str(age),lan_state_root='/mnt/pool/new',image=IMAGE)
    result=restore(encrypted,tmp_path/'restored',key,age=str(age),lan_state_root='/mnt/pool/new',image=IMAGE,gateway_image=GATEWAY)
    assert result['profile']=='wireguard' and result['sessions_revoked']
    assert all(p.read_bytes()==data for p,data in source.items())
    restored=tmp_path/'restored/state'
    assert (restored/'identity/gateway/wireguard.key').read_bytes()==(state/'identity/gateway/wireguard.key').read_bytes()
    assert (restored/'identity/client/channel.key').read_bytes()!=(state/'identity/client/channel.key').read_bytes()
    assert not list((restored/'gateway/channel').iterdir())
    raw=encrypted.read_bytes();bad=tmp_path/'bad.age';bad.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
    with pytest.raises((ValueError,tarfile.TarError,EOFError)):
        restore(bad,tmp_path/'refused',key,age=str(age),lan_state_root='/mnt/pool/new',image=IMAGE,gateway_image=GATEWAY)
    assert not (tmp_path/'refused').exists()
