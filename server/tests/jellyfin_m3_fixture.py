"""Disposable Jellyfin HTTP fixture. Never mounted by a production NOVA application."""
import copy
import json
import re
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading
import httpx


class JellyfinMembers:
    def __init__(self):
        self.sid='fixture-jellyfin';self.owner=uuid.uuid4().hex;self.users={};self.passwords={};self.tokens={}
        self.add(self.owner,'owner','owner-fixture-password',{'IsAdministrator':True,'IsDisabled':False})
    def add(self,uid,name,password,policy):
        self.users[uid]={'Id':uid,'Name':name,'Policy':policy};self.passwords[name]=password
    def __call__(self,request):
        path=request.url.path;method=request.method;data=json.loads(request.content) if request.content else {}
        token=re.search(r'Token="([A-Za-z0-9]+)"',request.headers.get('Authorization',''))
        uid=self.tokens.get(token[1]) if token else None;admin=uid==self.owner
        if path=='/System/Info/Public':return httpx.Response(200,json={'Id':self.sid,'ProductName':'Jellyfin Server'})
        if path=='/Users/AuthenticateByName':
            user=next((user for user in self.users.values() if user['Name']==data['Username']),None)
            if not user or self.passwords.get(data['Username'])!=data['Pw']:return httpx.Response(401)
            token=uuid.uuid4().hex;self.tokens[token]=user['Id']
            return httpx.Response(200,json={'AccessToken':token,'ServerId':self.sid,'User':copy.deepcopy(user)})
        if not uid:return httpx.Response(401)
        if path=='/Sessions/Logout':self.tokens.pop(token[1],None);return httpx.Response(204)
        if path=='/Users/New' and admin:
            new=uuid.uuid4().hex;self.add(new,data['Name'],data['Password'],{'IsAdministrator':False,'IsDisabled':False,'EnableAllFolders':True})
            return httpx.Response(200,json=copy.deepcopy(self.users[new]))
        if path=='/Users/Password' and admin:
            user=request.url.params['userId'];self.passwords[self.users[user]['Name']]=data['NewPw']
            self.tokens={key:value for key,value in self.tokens.items() if value!=user}
            return httpx.Response(204)
        match=re.fullmatch('/Users/([a-f0-9]{32})(/Policy)?',path)
        if match:
            target=match[1]
            if not admin and target!=uid:return httpx.Response(403)
            if method=='POST' and match[2] and admin:self.users[target]['Policy']=data;return httpx.Response(204)
            if method=='GET':return httpx.Response(200,json=copy.deepcopy(self.users[target]))
        return httpx.Response(403)


@contextmanager
def jellyfin_http():
    fixture=JellyfinMembers()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def handle_request(self):
            length=int(self.headers.get('Content-Length','0'))
            if length>16384:self.send_error(413);return
            body=self.rfile.read(length)
            request=httpx.Request(self.command,'http://127.0.0.1'+self.path,headers=dict(self.headers),content=body)
            response=fixture(request)
            self.send_response(response.status_code)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(response.content)))
            self.end_headers();self.wfile.write(response.content)
        do_GET=handle_request
        do_POST=handle_request
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:yield fixture,'http://127.0.0.1:'+str(server.server_port)
    finally:server.shutdown();server.server_close();worker.join(timeout=5)
