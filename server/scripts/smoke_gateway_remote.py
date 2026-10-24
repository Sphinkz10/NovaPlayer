"""Real Docker peer, authenticated media and kernel expiry during gateway freeze."""
import base64
import json
from pathlib import Path
import shutil
import subprocess
import time

PROBE = '''import httpx,json,ssl,sys,time
from pathlib import Path
request=json.load(sys.stdin)
context=ssl.create_default_context(cafile='/proof/ca.crt');context.minimum_version=ssl.TLSVersion.TLSv1_3
try:
 with httpx.Client(verify=context,trust_env=False,timeout=3) as client:
  def get():return client.get(request['origin']+request['path'],headers=request['headers'])
  response=get()
  if request.get('hold'):
   assert response.status_code==200
   Path('/proof/ready').write_text('ready')
   end=time.monotonic()+45
   while not Path('/proof/continue').exists():
    assert time.monotonic()<end
    time.sleep(.1)
   response=get()
  print(json.dumps({'status':response.status_code,'length':len(response.content)}))
except httpx.HTTPError as error:print(json.dumps({'blocked':True,'kind':type(error).__name__}))
'''


def prepare_probe(root,image):
    folder=root/'probe';folder.mkdir(mode=0o700)
    (folder/'probe.py').write_text(PROBE)
    return {'image':image,'command':['python','-c','import time;time.sleep(1800)'],'user':'0:0',
        'cap_drop':['ALL'],'cap_add':['NET_ADMIN','DAC_OVERRIDE'],'security_opt':['no-new-privileges:true'],
        'read_only':True,'healthcheck':{'disable':True},'networks':['nova_internal'],
        'volumes':[{'type':'bind','source':str(folder),'target':'/proof','read_only':False}],
        'tmpfs':['/tmp:rw,noexec,nosuid,size=4m']}


def verify_remote(root,bundle,project,client,info,admin,device,tokens,library,item):
    for name in ('ready','continue'):(root/'probe'/name).unlink(missing_ok=True)
    def command(*args,data=None,check=True):
        result=subprocess.run(['docker','compose','-p',project,*args],cwd=root,input=data,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
        if check and result.returncode:raise RuntimeError('Gateway lab command failed: '+args[0])
        return result
    def probe(*args,**kwargs):return command('exec','-T','probe',*args,**kwargs)
    def request(path='/api/v1/device/me',headers=None,port=None):
        data={'origin':'https://10.222.0.1:'+str(port or info['client'].rsplit(':',1)[1]),
            'path':path,'headers':headers or device}
        return json.loads(probe('python','/proof/probe.py',data=json.dumps(data).encode()).stdout)
    checks=[]
    shutil.copyfile(bundle/'NOVA-LAN-CA.crt',root/'probe/ca.crt')
    assert request().get('blocked') is True
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    key=X25519PrivateKey.generate()
    public=base64.b64encode(key.public_key().public_bytes_raw()).decode()
    private=root/'probe/private.key'
    private.write_bytes(base64.b64encode(key.private_bytes_raw())+b'\n');private.chmod(0o600)
    enrolled=client.post(info['client']+'/api/v1/device/wireguard',headers=device,json={'public_key':public})
    assert enrolled.status_code==200 and enrolled.json()['state']=='pending'
    assert client.get(info['client']+'/api/v1/device/wireguard/profile',headers=device).status_code==403
    assert client.post(info['control']+'/api/v1/admin/connect/wireguard/enrollments/'+tokens['device_id'],headers=admin,
        json={'revision':enrolled.json()['revision'],'approve':True}).status_code==200
    for _ in range(40):
        result=client.get(info['client']+'/api/v1/device/wireguard/profile',headers=device)
        if result.status_code==200:break
        assert result.status_code==503;time.sleep(.5)
    else:raise AssertionError('Authenticated gateway profile not ready')
    profile=result.json();assert profile['device_id']==tokens['device_id'] and profile['public_key']==public
    endpoint_ip=probe('python','-c',"import socket;print(socket.gethostbyname('nova-gateway'))").stdout.decode().strip()
    probe('ip','link','add','wg0','type','wireguard')
    probe('wg','set','wg0','private-key','/proof/private.key','peer',profile['gateway_public_key'],
        'allowed-ips',profile['allowed_ip'],'endpoint',endpoint_ip+':51820','persistent-keepalive','5')
    probe('ip','addr','add',profile['address'],'dev','wg0');probe('ip','link','set','wg0','mtu','1280','up')
    probe('ip','route','add',profile['allowed_ip'],'dev','wg0')
    for _ in range(20):
        if request().get('status')==200:break
        time.sleep(.5)
    else:raise AssertionError('Real Docker WireGuard peer did not reach pinned HTTPS')
    checks.extend(['generated_isolated_container_stack','authenticated_profile_only_after_approval','real_wireguard_pinned_tls13_identity'])
    catalog='/api/v1/media/libraries/'+library+'/items'
    assert request(catalog)['status']==200
    assert request(catalog+'/'+item+'/stream',{**device,'Range':'bytes=0-255'})=={'status':206,'length':256}
    assert request('/api/v1/admin/overview')['status']==404
    assert request(port=9443).get('blocked') is True
    checks.extend(['actual_jellyfin_catalogue_over_tunnel','actual_jellyfin_range_video_over_tunnel','remote_admin_surface_blocked'])
    # Keep the same TLS/HTTP connection alive across a gateway freeze. The
    # client container remains running in the shared namespace, exposing bugs
    # where conntrack ESTABLISHED would otherwise bypass an expiring allowlist.
    held=subprocess.Popen(['docker','compose','-p',project,'exec','-T','probe','python','/proof/probe.py'],cwd=root,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    held.stdin.write(json.dumps({'origin':profile['client_origin'],'path':'/api/v1/device/me','headers':device,'hold':True}).encode())
    held.stdin.close()
    try:
        for _ in range(40):
            if (root/'probe/ready').exists():break
            time.sleep(.1)
        else:raise AssertionError('Persistent TLS connection was not established')
        command('pause','nova-gateway')
        time.sleep(16)
        (root/'probe/continue').write_text('go')
        held.wait(timeout=10)
        assert held.returncode==0 and json.loads(held.stdout.read()).get('blocked') is True
        assert request().get('blocked') is True
        checks.append('kernel_deadline_blocks_existing_and_new_https_while_gateway_frozen')
    finally:
        command('unpause','nova-gateway',check=False)
        if held.poll() is None:held.kill();held.wait(timeout=5)
    for _ in range(20):
        if request().get('status')==200:break
        time.sleep(.5)
    else:raise AssertionError('Gateway did not recover from freeze')
    old_address=profile['address']
    command('restart','nova-gateway','nova-client')
    for _ in range(30):
        if request().get('status')==200:break
        time.sleep(.5)
    else:raise AssertionError('Gateway namespace restart did not recover')
    for _ in range(30):
        result=client.get(info['client']+'/api/v1/device/wireguard/profile',headers=device)
        if result.status_code==200:break
        time.sleep(.2)
    assert result.status_code==200 and result.json()['address']==old_address
    checks.append('container_restart_preserves_identity_and_peer_address')
    # Revoke enrollment without revoking the device session: the network peer
    # itself must disappear, independently of HTTP credential rejection.
    assert client.post(info['control']+'/api/v1/admin/connect/wireguard/enrollments/'+tokens['device_id'],headers=admin,
        json={'revision':profile['revision'],'approve':False}).status_code==200
    time.sleep(4)
    assert request().get('blocked') is True
    assert client.get(info['client']+'/api/v1/device/wireguard/profile',headers=device).status_code==403
    checks.append('owner_enrollment_revocation_removes_remote_media_access')
    return {'result':'passed','checks':checks,'physical_nas':False,'physical_tv':False,
        'gateway':'generated Docker namespace, native kernel WireGuard, nftables source deadlines',
        'media':'real Jellyfin catalogue and 256-byte HTTP Range video through the tunnel'}
