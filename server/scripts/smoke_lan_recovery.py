"""Called only by the disposable Docker LAN gate; no existing server is touched."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def run(root,bundle,image,project,info,client,compose,*,owner,admin,credentials,family,family_password,tokens,selected,profile):
    config=json.loads((root/'compose.yaml').read_text());state=bundle/'copiar-para-nas'
    directory=info['tv_directory'];control=info['control'];media=info['client']
    directory_owner=client.post(directory+'/api/v1/directory/login',json=owner).json()
    owner_header={'Authorization':'Bearer '+directory_owner['access_token']}
    family_header={'Authorization':'Bearer '+family['access_token']}
    registered=client.get(directory+'/api/v1/directory/servers',headers=family_header).json()['servers'][0]['record']['payload']
    entry=registered['entry_id']
    old_proof=client.post(directory+'/api/v1/directory/assertions',headers=family_header,json={'entry_id':entry}).json()
    agent=client.post(directory+'/api/v1/directory/servers/'+entry+'/renewal-credential',headers=owner_header).json()['credential']
    def core_json(code,payload):
        result=subprocess.run(['docker','compose','-p',project,'exec','-T','nova-admin','python','-c',code],cwd=root,
            input=json.dumps(payload),text=True,capture_output=True)
        if result.returncode:raise RuntimeError('Isolated Jellyfin recovery fixture failed; raw output withheld')
        return json.loads(result.stdout)
    old_jf=core_json('''
import json,sys,httpx
value=json.load(sys.stdin)
with httpx.Client(base_url='http://jellyfin:8096',trust_env=False,timeout=10) as client:
    response=client.post('/Users/AuthenticateByName',headers={'Authorization':'MediaBrowser Client="NOVA CI", Device="CI", DeviceId="lan-recovery", Version="1"'},
        json={'Username':value['username'],'Pw':value['password']})
    assert response.status_code==200
    print(json.dumps({'token':response.json()['AccessToken']}))
''',credentials)['token']
    compose('stop')
    identity_files=[state/'directory/directory-identity.key',*list((state/'nova').glob('*.key')),
                    *[p for p in (state/'identity').rglob('*') if p.is_file()]]
    hashes={p.relative_to(state).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in identity_files}
    keys=root/'recovery-keys';backups=root/'backups';recovered=root/'recovered'
    for folder in (keys,backups,recovered):folder.mkdir(mode=0o700)
    def helper(arguments,mounts,check=True):
        command=['docker','run','--rm','--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
                 '--user',f'{os.getuid()}:{os.getgid()}']
        for host,guest,mode in mounts:command+=['-v',f'{host}:{guest}:{mode}']
        result=subprocess.run([*command,image,*arguments],capture_output=True,text=True)
        if check and result.returncode:raise RuntimeError('LAN maintenance '+arguments[0]+' failed; raw output withheld')
        return result
    for name in ('recovery','wrong'):helper(['age-keygen','-o','/keys/'+name+'.key'],[(keys,'/keys','rw')])
    recipient=helper(['age-keygen','-y','/keys/recovery.key'],[(keys,'/keys','ro')]).stdout.strip()
    helper(['python','scripts/recovery.py','backup','--state','/state','--output','/backups/nova.age',
            '--recipient',recipient,'--deployment','/deployment.json','--services-stopped'],
        [(state,'/state','rw'),(backups,'/backups','rw'),(bundle/'instalar-no-truenas.yaml','/deployment.json','ro')])
    ciphertext=(backups/'nova.age').read_bytes()
    assert b'SQLite format 3' not in ciphertext and b'BEGIN PRIVATE KEY' not in ciphertext
    for name,data,key in (('tampered',ciphertext[:-1]+bytes([ciphertext[-1]^1]),'recovery'),
                           ('truncated',ciphertext[:-80],'recovery'),('wrong-key',ciphertext,'wrong')):
        (backups/(name+'.age')).write_bytes(data)
        failed=helper(['python','scripts/recovery.py','restore','--input','/backups/'+name+'.age','--output','/restore/'+name,
            '--identity','/keys/'+key+'.key','--lan-state-root','/mnt/pool/recovered','--image','ghcr.io/sphinkz10/nova-core@sha256:'+'a'*64],
            [(backups,'/backups','ro'),(keys,'/keys','ro'),(recovered,'/restore','rw')],check=False)
        assert failed.returncode!=0 and not (recovered/name).exists()
    arguments=['python','scripts/recovery.py','restore','--input','/backups/nova.age','--output','/restore/accepted',
        '--identity','/keys/recovery.key','--lan-state-root','/mnt/pool/recovered','--image','ghcr.io/sphinkz10/nova-core@sha256:'+'a'*64]
    mounts=[(backups,'/backups','ro'),(keys,'/keys','ro'),(recovered,'/restore','rw')]
    restored=json.loads(helper(arguments,mounts).stdout);assert restored['profile']=='lan' and restored['identity_preserved']
    assert helper(arguments,mounts,check=False).returncode!=0
    accepted=recovered/'accepted';new_state=accepted/'state'
    for name,digest in hashes.items():
        path=new_state/name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest and path.stat().st_mode&0o077==0
    assert not list(new_state.rglob('*ca.key'))
    rendered=json.loads((accepted/'instalar-no-truenas.yaml').read_text())
    media_hosts={m['target']:m['source'] for m in config['services']['jellyfin']['volumes'] if m['target'].startswith('/media/')}
    for name,service in rendered['services'].items():
        if name!='jellyfin':service['image']=image
        for mount in service['volumes']:
            if mount['source'].startswith('/mnt/pool/recovered/'):
                mount['source']=str(new_state/mount['source'].removeprefix('/mnt/pool/recovered/'))
            elif mount['target'] in media_hosts:mount['source']=media_hosts[mount['target']]
            else:raise ValueError('Unexpected restored fixture mount')
    compose('down');(root/'compose.yaml').write_text(json.dumps(rendered));compose('up','-d')
    for _ in range(120):
        try:
            if client.get(directory+'/api/v1/directory/bootstrap').json()==profile and client.get(control+'/api/v1/health/live').status_code==200:break
        except Exception:pass
        time.sleep(1)
    else:raise AssertionError('Restored LAN services did not become ready')
    assert client.get(control+'/api/v1/admin/overview',headers=admin).status_code==401
    assert client.get(media+'/api/v1/device/me',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==401
    assert client.post(media+'/api/v1/device/refresh',json={'refresh_token':tokens['refresh_token']}).status_code!=200
    assert client.get(directory+'/api/v1/directory/servers',headers=family_header).status_code==401
    assert client.post(directory+'/api/v1/directory/renewals/challenges',headers={'Authorization':'Bearer '+agent},json=registered['descriptor']).status_code==401
    fresh=client.post(control+'/api/v1/admin/login',json=owner);assert fresh.status_code==200
    admin={'Authorization':'Bearer '+fresh.json()['access_token']}
    status=client.get(control+'/api/v1/admin/directory',headers=admin).json()
    assert not status['renewal_available'] and not status['automatic_renewal'] and status['state']=='recovery_republish_required'
    fresh_family=client.post(directory+'/api/v1/directory/login',json={'username':'alice','password':family_password}).json()
    family_header={'Authorization':'Bearer '+fresh_family['access_token']}
    assert client.get(directory+'/api/v1/directory/servers',headers=family_header).json()['servers']==[]
    for _ in range(120):
        overview=client.get(control+'/api/v1/admin/overview',headers=admin)
        if overview.status_code==200 and overview.json()['jellyfin']['state']=='ready':break
        time.sleep(1)
    else:raise AssertionError('Restored Jellyfin not ready')
    assert core_json('''
import json,sys,httpx
token=json.load(sys.stdin)['token']
with httpx.Client(trust_env=False,timeout=10) as client:
    print(json.dumps({'status':client.get('http://jellyfin:8096/Users/Me',headers={'Authorization':'MediaBrowser Token="'+token+'"'}).status_code}))
''',{'token':old_jf})['status'] in (401,403)
    assert client.post(control+'/api/v1/admin/setup/jellyfin/verify',headers=admin,json=credentials).status_code==200
    assert client.post(control+'/api/v1/admin/directory/publish',headers=admin,json={**owner,'name':'Casa LAN recuperada'}).status_code==200
    assert old_proof['payload']['expires_at']>time.time(), 'Old proof expired before the recovery barrier check'
    assert client.post(media+'/api/v1/device/authorize',json={'label':'Old proof TV','assertion':old_proof}).status_code==403
    proof=client.post(directory+'/api/v1/directory/assertions',headers=family_header,json={'entry_id':entry}).json()
    granted=client.post(media+'/api/v1/device/authorize',json={'label':'Recovered TV','assertion':proof});assert granted.status_code==201
    grant=granted.json();review=client.post(control+'/api/v1/admin/devices/inspect',headers=admin,json={'user_code':grant['user_code']}).json()
    decision={'user_code':grant['user_code'],'request_id':review['request_id'],'approve':True}
    assert client.post(control+'/api/v1/admin/devices/decision',headers=admin,json=decision).status_code==409
    assert client.post(control+'/api/v1/admin/members',headers=admin,json={**credentials,'subject':family['account_id'],'libraries':[selected]}).status_code==200
    review=client.post(control+'/api/v1/admin/devices/inspect',headers=admin,json={'user_code':grant['user_code']}).json();decision['request_id']=review['request_id']
    assert client.post(control+'/api/v1/admin/devices/decision',headers=admin,json=decision).status_code==200
    token=client.post(media+'/api/v1/device/token',json={'device_code':grant['device_code']}).json()['access_token']
    device={'Authorization':'Bearer '+token}
    catalog=client.get(media+'/api/v1/media/libraries/'+selected+'/items',headers=device).json()
    response=client.get(media+'/api/v1/media/libraries/'+selected+'/items/'+catalog['items'][0]['id']+'/stream',headers={**device,'Range':'bytes=0-255'})
    assert response.status_code==206 and len(response.content)==256
    return {'result':'passed','format':2,'physical_truenas':False,'checks':['age_encrypted_complete_state','tamper_truncation_wrong_key_refused',
        'existing_destination_refused','identities_and_tls_preserved','safe_yaml_new_dataset','four_restored_services',
        'admin_device_directory_sessions_revoked','jellyfin_sessions_revoked','republication_required','pre_restore_assertion_refused',
        'media_requires_fresh_grant_and_approval','catalog_and_video_after_reassociation']}
