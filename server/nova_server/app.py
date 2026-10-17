"""NOVA Core local-only owner administration, first installable increment.

This is NOT an Internet-facing API or universal NOVA Directory.
"""
from __future__ import annotations
import os
import re
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .security import hash_password, verify_password, token_matches, new_session_token
from .storage import Store
from .jellyfin import probe_jellyfin

USERNAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_.-]{2,39}$')
DUMMY_HASH = '$argon2id$v=19$m=65536,t=3,p=2$bsLfU/8cH1R+4e68utTSNQ$8Tk5/U5Y6zx5/ZrURl0G7DtU5y3EXazaQ+3mifoBRLI'

class BootstrapPayload(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=14, max_length=1024)

class LoginPayload(BaseModel):
    username: str = Field(min_length=1,max_length=40)
    password: str = Field(min_length=1,max_length=1024)


def make_app(state_dir=None, jellyfin_url=None):
    state_dir=Path(state_dir or os.environ.get('NOVA_STATE_DIR','./state/nova'))
    jellyfin_url=jellyfin_url or os.environ.get('NOVA_JELLYFIN_URL','http://jellyfin:8096')
    store=Store(state_dir)
    api=FastAPI(title='NOVA Core (local bootstrap)', docs_url=None, redoc_url=None,openapi_url=None)
    api.state.store=store
    api.state.jellyfin_url=jellyfin_url

    @api.middleware('http')
    async def security_headers(req: Request, call_next):
        response=await call_next(req)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Permissions-Policy']='camera=(),microphone=(),geolocation=()'
        response.headers['Content-Security-Policy']=(
            "default-src 'none'; base-uri 'none'; object-src 'none'; "
            "script-src 'self'; style-src 'self'; img-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; form-action 'none'")
        return response

    async def owner(request: Request):
        bearer=request.headers.get('Authorization','')
        if not bearer.startswith('Bearer '):
            raise HTTPException(401,'Sessão necessária.',headers={'WWW-Authenticate':'Bearer'})
        token=bearer[7:]
        if len(token)<30 or not store.session_valid(token):
            raise HTTPException(401,'Sessão inválida ou expirada.',headers={'WWW-Authenticate':'Bearer'})
        return token

    @api.get('/api/v1/health/live')
    def live():
        return {'status':'up','component':'nova-core'}

    @api.get('/api/v1/status')
    def status():
        return {'product':'NOVA Server','version':'0.1.0',
                'owner_setup_required':not store.has_admin(),
                'remote_access_enabled':False,
                'directory_enabled':False,
                'jellyfin_installed_as_compose_service':True}

    @api.post('/api/v1/admin/bootstrap',status_code=201)
    def bootstrap(payload:BootstrapPayload, request:Request):
        if store.has_admin():
            raise HTTPException(409,'O proprietário já foi criado.')
        if not USERNAME_PATTERN.fullmatch(payload.username):
            raise HTTPException(422,'Nome de utilizador inválido.')
        bootstrap_file=state_dir/'bootstrap.token'
        try:
            expected=bootstrap_file.read_text(encoding='ascii').strip()
        except (FileNotFoundError,PermissionError,UnicodeError):
            raise HTTPException(403,'Token de primeira instalação indisponível.')
        supplied=request.headers.get('X-NOVA-Bootstrap','')
        if not supplied or len(supplied)>256 or not token_matches(supplied,expected):
            raise HTTPException(403,'Token de instalação inválido.')
        try:
            hashed=hash_password(payload.password)
        except ValueError as e:
            raise HTTPException(422,str(e))
        if not store.bootstrap(payload.username,hashed):
            raise HTTPException(409,'O proprietário já foi criado.')
        bootstrap_file.unlink(missing_ok=True)
        return {'ok':True,'admin':payload.username,'remote_access_enabled':False}

    @api.post('/api/v1/admin/login')
    def login(payload: LoginPayload, request: Request):
        ip=request.client.host if request.client else 'unknown'
        if store.login_blocked(ip):
            raise HTTPException(429,'Demasiadas tentativas; aguarda 15 minutos.')
        admin=store.get_admin(payload.username)
        if not verify_password(admin[1] if admin is not None else DUMMY_HASH, payload.password) or admin is None:
            store.failed_login(ip)
            raise HTTPException(401,'Credenciais inválidas.')
        store.clear_login_attempts(ip)
        token=new_session_token()
        store.save_session(token,lifetime=3600)
        return {'access_token':token,'token_type':'bearer','expires_in':3600}

    @api.post('/api/v1/admin/logout')
    def logout(token:str=Depends(owner)):
        store.revoke_session(token)
        return {'ok':True}

    @api.get('/api/v1/admin/overview')
    async def overview(token:str=Depends(owner)):
        result=await probe_jellyfin(jellyfin_url)
        return {'nova_core':'running','jellyfin':result,
                'library_roots':[{'name':'source-a','container_path':'/media/source-a', 'read_only':True},
                                 {'name':'source-b','container_path':'/media/source-b', 'read_only':True}],
                'connect':{'state':'disabled','reason':'P03 pending secure remote design'},
                'directory':{'state':'not_implemented'},
                'admin_interface':{'exposure':'loopback_only_required'}}

    @api.get('/',response_class=HTMLResponse)
    def home():
        return (Path(__file__).parent/'static'/'index.html').read_text(encoding='utf-8')

    api.mount('/static',StaticFiles(directory=str(Path(__file__).parent/'static')),name='static')
    return api

app=make_app()
