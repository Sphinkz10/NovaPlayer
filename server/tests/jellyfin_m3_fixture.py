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
        self.media_items={};self.media_content=None;self.media_events=[];self.media_ranges=[]
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
        if re.fullmatch('/Items/[a-f0-9]{32}/Ancestors',path) and self.media_items:
            target=path.split('/')[2]
            return httpx.Response(200,json=[{'Id':library} for library,items in self.media_items.items()
                if any(item['Id']==target for item in items)])
        if path=='/Items' and self.media_items:
            library=request.url.params.get('ParentId')
            allowed=self.users[uid]['Policy'].get('EnabledFolders',[])
            values=copy.deepcopy(self.media_items.get(library,[])) if library in allowed else []
            if request.url.params.get('Ids'):values=[v for v in values if v['Id']==request.url.params['Ids']]
            search=request.url.params.get('SearchTerm','').casefold()
            values=[v for v in values if search in v['Name'].casefold()]
            start=int(request.url.params.get('StartIndex',0));limit=int(request.url.params.get('Limit',24))
            return httpx.Response(200,json={'Items':values[start:start+limit],'TotalRecordCount':len(values)})
        if path.startswith('/Sessions/Playing') and self.media_items:
            for library,values in self.media_items.items():
                if library not in self.users[uid]['Policy'].get('EnabledFolders',[]):continue
                for item in values:
                    if item['Id']==data.get('ItemId'):
                        item.setdefault('UserData',{})['PlaybackPositionTicks']=data['PositionTicks']
                        self.media_events.append({'path':path,**data});return httpx.Response(204)
            return httpx.Response(404)
        if re.fullmatch('/Videos/[a-f0-9]{32}/stream',path) and self.media_content is not None:
            item_id=path.split('/')[2]
            if not any(item['Id']==item_id for library,items in self.media_items.items()
                       if library in self.users[uid]['Policy'].get('EnabledFolders',[]) for item in items):
                return httpx.Response(404)
            content=self.media_content;first=0;last=len(content)-1;code=200
            value=request.headers.get('Range')
            if value:
                match=re.fullmatch(r'bytes=(\d+)-(\d*)',value)
                if not match:return httpx.Response(416)
                first=int(match[1]);last=min(int(match[2]),last) if match[2] else last;code=206
                if first>last:return httpx.Response(416)
                self.media_ranges.append(first)
            headers={'Content-Type':'video/mp4','Content-Length':str(last-first+1),'Accept-Ranges':'bytes'}
            if code==206:headers['Content-Range']=f'bytes {first}-{last}/{len(content)}'
            return httpx.Response(code,content=content[first:last+1],headers=headers)
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
            for name,value in response.headers.items():self.send_header(name,value)
            self.end_headers()
            try:self.wfile.write(response.content)
            except (BrokenPipeError,ConnectionResetError):pass
        do_GET=handle_request
        do_POST=handle_request
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:yield fixture,'http://127.0.0.1:'+str(server.server_port)
    finally:server.shutdown();server.server_close();worker.join(timeout=5)
