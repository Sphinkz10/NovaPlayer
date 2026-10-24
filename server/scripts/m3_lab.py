"""Shared disposable M3 fixture: Directory, two NOVA identities and isolated HTTPS APIs."""
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import time
import uuid

import httpx

SERVER=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SERVER))
from nova_directory.client import DirectoryClient
from nova_directory.store import Registry
from nova_server.directory_control import DirectoryControl
from nova_server.security import hash_password
from nova_server.storage import Store
from smoke_directory_tls import make_certificate
from smoke_devices_tls import free_port,ready,stop


class M3Lab:
    def __init__(self,root,jellyfin_url,*,state=None,owner=None,jellyfin_credentials=None,libraries=None,jellyfin_id=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.jellyfin_url=jellyfin_url
        self.owner=owner or {'username':'owner','password':secrets.token_urlsafe(32)}
        self.jellyfin_credentials=jellyfin_credentials or {'username':'owner','password':'owner-fixture-password'}
        self.password=secrets.token_urlsafe(32)
        ports=set()
        while len(ports)<4:ports.add(free_port())
        self.admin_port,self.api_port,self.api_b_port,self.directory_port=sorted(ports)
        self.origin=f'https://127.0.0.1:{self.api_port}';self.origin_b=f'https://127.0.0.1:{self.api_b_port}'
        self.directory_origin=f'https://127.0.0.1:{self.directory_port}';self.admin_origin=f'http://127.0.0.1:{self.admin_port}'
        self.processes=[];self.api_process=None
        self.store=Store(state or self.root/'nova-a');self.store_b=Store(self.root/'nova-b')
        for store in (self.store,self.store_b):
            if not store.has_admin():store.bootstrap(self.owner['username'],hash_password(self.owner['password']))
        self.libraries=libraries or [{'id':uuid.uuid4().hex,'name':'Biblioteca '+name} for name in ('A','B')]
        if libraries:
            report={'server_id':jellyfin_id,'observed_at':int(time.time()),'libraries':[
                {**lib,'indexed_items':0,'paths':['/media/source-'+('a' if index==0 else 'b')]} for index,lib in enumerate(self.libraries)]}
            for store in (self.store,self.store_b):
                with store._db() as db:db.execute('UPDATE jellyfin_setup SET server_id=?,report=?',(jellyfin_id,json.dumps(report)))
        for name in ('directory-tls','api-tls','api-b-tls'):(self.root/name).mkdir(exist_ok=True)
        self.ca,self.directory_key=make_certificate(self.root/'directory-tls')
        self.cert,self.key=make_certificate(self.root/'api-tls')
        self.cert_b,self.key_b=make_certificate(self.root/'api-b-tls')
        self.registry=Registry(self.root/'directory',self.directory_origin)
        self.accounts={name:self.registry.create_account(name,self.password) for name in ('operator','alice','bruno')}
        self.admin=None

    def launch(self,command,env=None):
        process=subprocess.Popen([sys.executable,*command],cwd=SERVER,env={**os.environ,**(env or {})},
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.processes.append(process);return process

    def api_env(self,b=False):
        return {'NOVA_STATE_DIR':str(self.store_b.dir if b else self.store.dir),'NOVA_JELLYFIN_URL':self.jellyfin_url,
                'NOVA_CLIENT_ORIGIN':self.origin_b if b else self.origin,
                'NOVA_CLIENT_CERT':str(self.cert_b if b else self.cert),'NOVA_CLIENT_KEY':str(self.key_b if b else self.key),
                'NOVA_DIRECTORY_ORIGIN':self.directory_origin,'NOVA_DIRECTORY_CA':str(self.ca)}

    def __enter__(self):
        try:
            self.launch(['-m','nova_directory','serve','--state',str(self.registry.root),'--origin',self.directory_origin,
                         '--certificate',str(self.ca),'--key',str(self.directory_key)])
            control=DirectoryControl(self.store.dir,self.directory_origin,self.ca,self.origin,self.cert)
            control_b=DirectoryControl(self.store_b.dir,self.directory_origin,self.ca,self.origin_b,self.cert_b)
            # Core startup can parse trust files before Directory readiness; wait using strict TLS.
            probe=DirectoryClient(self.directory_origin,self.ca)
            try:ready(probe.http,'/api/v1/directory/health',self.processes[0],200)
            finally:probe.close()
            admin_process=self.launch(['-m','uvicorn','nova_server.app:app','--host','127.0.0.1','--port',str(self.admin_port),
                                      '--no-proxy-headers','--no-access-log'],self.api_env())
            self.admin=httpx.Client(base_url=self.admin_origin,trust_env=False,timeout=60)
            ready(self.admin,'/api/v1/health/live',admin_process,200)
            result=self.admin.post('/api/v1/admin/login',json=self.owner);assert result.status_code==200
            self.admin.headers['Authorization']='Bearer '+result.json()['access_token']
            assert self.admin.post('/api/v1/admin/directory/identity').status_code==200
            published=self.admin.post('/api/v1/admin/directory/publish',json={
                'username':'operator','password':self.password,'name':'Casa A · Cinema'})
            assert published.status_code==200,published.text
            self.entry=published.json()['entry_id']
            control_b.initialize();self.entry_b=control_b.operate('publish','operator',self.password,'Casa B')['entry_id']
            for user in ('alice','bruno'):self.registry.membership(self.accounts['operator'],self.entry,user,True)
            self.registry.membership(self.accounts['operator'],self.entry_b,'bruno',True)
            self.api_process=self.launch(['-m','nova_server.client_api'],self.api_env())
            self.launch(['-m','nova_server.client_api'],self.api_env(True))
            self.tv=self.client();self.tv_b=self.client(b=True)
            ready(self.tv,'/api/v1/device/me',self.api_process,401)
            ready(self.tv_b,'/api/v1/device/me',self.processes[-1],401)
            return self
        except BaseException:
            self.__exit__(None,None,None);raise

    def client(self,b=False):
        context=ssl.create_default_context(cafile=str(self.cert_b if b else self.cert))
        return httpx.Client(base_url=self.origin_b if b else self.origin,verify=context,trust_env=False,timeout=20)

    def directory_client(self,user):
        client=DirectoryClient(self.directory_origin,self.ca);client.login(user,self.password);return client

    def profile(self):
        return {'version':1,'purpose':'nova-directory-bootstrap','origin':self.directory_origin,
                'certificate_pem':self.ca.read_text(),'public_key':self.registry.identity_public}

    def configure_member(self,subject,index):
        result=self.admin.post('/api/v1/admin/members',json={**self.jellyfin_credentials,'subject':subject,
                              'libraries':[self.libraries[index]['id']]})
        assert result.status_code==200,result.text
        assert result.json()['jellyfin_policy_verified'] and not result.json()['administrator']
        return result.json()

    def approve(self,code,index=0):
        reviewed=self.admin.post('/api/v1/admin/devices/inspect',json={'user_code':code})
        assert reviewed.status_code==200
        review=reviewed.json();assert review['account_id'] in self.accounts.values()
        if not review['member_configured']:self.configure_member(review['account_id'],index)
        result=self.admin.post('/api/v1/admin/devices/decision',json={'user_code':code,'request_id':review['request_id'],'approve':True})
        assert result.status_code==200,result.text
        return review

    def pair(self,user,index):
        directory=self.directory_client(user)
        try:assertion=directory.request('POST','assertions',{'entry_id':self.entry})
        finally:directory.close()
        response=self.tv.post('/api/v1/device/authorize',json={'label':'TV '+user,'assertion':assertion})
        assert response.status_code==201,response.text
        grant=response.json();self.approve(grant['user_code'],index)
        tokens=self.tv.post('/api/v1/device/token',json={'device_code':grant['device_code']})
        assert tokens.status_code==200,tokens.text
        return tokens.json(),assertion

    def rotate_certificate(self):
        self.tv.close();stop(self.api_process)
        old=self.cert.read_bytes();make_certificate(self.root/'api-tls')
        assert self.cert.read_bytes()!=old
        self.api_process=self.launch(['-m','nova_server.client_api'],self.api_env())
        self.tv=self.client();ready(self.tv,'/api/v1/device/me',self.api_process,401)
        result=self.admin.post('/api/v1/admin/directory/renew')
        assert result.status_code==200,result.text
        return result.json()

    def __exit__(self,*args):
        for name in ('tv','tv_b','admin'):
            client=getattr(self,name,None)
            if client:
                if name=='admin':
                    try:client.post('/api/v1/admin/logout')
                    except httpx.HTTPError:pass
                client.close()
        for process in reversed(self.processes):
            if process.poll() is None:stop(process)
