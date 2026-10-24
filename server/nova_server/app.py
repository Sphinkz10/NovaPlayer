"""NOVA Core local-only owner administration, first installable increment.

This is NOT an Internet-facing API or universal NOVA Directory.
"""
from __future__ import annotations
import os
import re
import threading
import asyncio
from contextlib import asynccontextmanager,suppress
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from .security import hash_password, verify_password, token_matches, new_session_token
from .storage import Store
from .jellyfin import probe_jellyfin
from .connect import ConnectDraft, provider_catalog
from .setup import JellyfinSetup, SetupRequest, Credentials, SetupError
from .devices import Devices, DeviceError
from .device_api import Payload, UserCode, DeviceDecision, device_error
from .client_api import SmallBody
from .members import MemberConfiguration
from .wireguard import WireGuardEnrollments, EnrollmentDecision
from .tailscale_control import TailscaleControl,TailscaleDecision

USERNAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_.-]{2,39}$')
DUMMY_HASH = '$argon2id$v=19$m=65536,t=3,p=2$bsLfU/8cH1R+4e68utTSNQ$8Tk5/U5Y6zx5/ZrURl0G7DtU5y3EXazaQ+3mifoBRLI'
PASSWORD_SLOTS = threading.BoundedSemaphore(2)

class BootstrapPayload(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=14, max_length=1024)

class LoginPayload(BaseModel):
    username: str = Field(min_length=1,max_length=40)
    password: str = Field(min_length=1,max_length=1024)


class DirectoryCredentials(Payload):
    username: str = Field(min_length=3, max_length=40, pattern=r'^[a-z][a-z0-9_.-]{2,39}$')
    password: str = Field(min_length=1, max_length=1024)


class DirectoryPublication(DirectoryCredentials):
    name: str = Field(min_length=1, max_length=64)


class DirectoryNewAccount(DirectoryCredentials):
    member_username:str=Field(pattern=r'^[a-z][a-z0-9_.-]{2,39}$')
    member_password:str=Field(min_length=14,max_length=1024)


def make_app(state_dir=None, jellyfin_url=None, *, allowed_hosts=None, jellyfin_server_id=None, directory_options=None,
             gateway_options=None,tailscale_options=None):
    state_dir=Path(state_dir or os.environ.get('NOVA_STATE_DIR','./state/nova'))
    jellyfin_url=jellyfin_url or os.environ.get('NOVA_JELLYFIN_URL','http://jellyfin:8096')
    store=Store(state_dir)
    api=FastAPI(title='NOVA Core (local bootstrap)', docs_url=None, redoc_url=None,openapi_url=None)
    api.state.store=store
    devices = Devices(store)
    api.state.devices = devices
    tailscale_options=tailscale_options or TailscaleControl.options()
    tailscale_control=TailscaleControl.local(store,**tailscale_options) if tailscale_options else None
    api.state.tailscale_control=tailscale_control
    if directory_options is None and os.environ.get('NOVA_DIRECTORY_ORIGIN'):
        directory_options = dict(origin=os.environ['NOVA_DIRECTORY_ORIGIN'],
            ca=os.environ.get('NOVA_DIRECTORY_CA',''), client_origin=os.environ.get('NOVA_CLIENT_ORIGIN',''),
            certificate=os.environ.get('NOVA_CLIENT_CERT',''))
    directory_control = None
    if directory_options:
        from .directory_control import DirectoryControl, ControlError, safe_operation
        directory_control = DirectoryControl(state_dir, **directory_options)
    api.state.directory_control = directory_control
    if gateway_options is None and os.environ.get('NOVA_WIREGUARD_CHANNEL_DIR'):
        gateway_options = {'directory': os.environ['NOVA_WIREGUARD_CHANNEL_DIR'],
                           'secret_file': os.environ.get('NOVA_WIREGUARD_CHANNEL_KEY_FILE', '')}
    gateway_publisher = None
    if gateway_options:
        from .gateway_channel import GatewayChannel, GatewayPublisher
        gateway_publisher = GatewayPublisher(WireGuardEnrollments(store), GatewayChannel(**gateway_options))
    api.state.gateway_publisher = gateway_publisher
    @asynccontextmanager
    async def directory_runtime(app):
        task=None
        gateway_task=None
        gateway_lock=None
        async def emit_gateway_plan():
            emission=asyncio.create_task(asyncio.to_thread(gateway_publisher.publish))
            try:await asyncio.shield(emission)
            except asyncio.CancelledError:
                # A cancelled to_thread keeps running. Join it before withdrawing
                # the plan and releasing the publisher lock.
                with suppress(Exception):await emission
                raise
        if gateway_publisher:
            from .gateway_service import exclusive
            # Exactly one Core process publishes authoritative plans per volume.
            gateway_lock=exclusive(gateway_publisher.channel.directory, 'publisher')
            gateway_lock.__enter__()
            try:
                await emit_gateway_plan()
                gateway_publisher.active=True
            except BaseException:
                gateway_lock.__exit__(None,None,None)
                raise
            async def publish_gateway():
                while True:
                    await asyncio.sleep(2)
                    try:
                        await emit_gateway_plan()
                        gateway_publisher.active=True
                    except Exception:
                        gateway_publisher.active=False
            gateway_task=asyncio.create_task(publish_gateway())
        if directory_control:
            directory_control.worker_active=True
            async def renew():
                while True:
                    await asyncio.sleep(60)
                    try:await asyncio.to_thread(safe_operation,lambda:directory_control.renew_if_due())
                    except Exception:pass # Retry bounded renewal; never log credentials or raw remote failures.
            task=asyncio.create_task(renew())
        try:yield
        finally:
            if gateway_publisher:
                gateway_publisher.active=False
                if gateway_task:
                    gateway_task.cancel()
                    with suppress(asyncio.CancelledError):await gateway_task
                # Missing transport causes removal on the worker's next tick;
                # never delete the durable address database on a Core restart.
                with suppress(OSError):(gateway_publisher.channel.directory/'plan.json').unlink(missing_ok=True)
                gateway_lock.__exit__(None,None,None)
            if directory_control:directory_control.worker_active=False
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):await task
    api.router.lifespan_context=directory_runtime
    api.add_exception_handler(DeviceError, device_error)
    api.state.jellyfin_url=jellyfin_url
    jellyfin_server_id = jellyfin_server_id or os.environ.get('NOVA_JELLYFIN_SERVER_ID')
    api.state.jellyfin_setup = JellyfinSetup(store, jellyfin_url, jellyfin_server_id)
    hosts = allowed_hosts if allowed_hosts is not None else ['127.0.0.1', 'localhost']
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts, www_redirect=False)
    api.add_middleware(SmallBody, maximum=16384)

    @api.exception_handler(RequestValidationError)
    async def invalid_payload(request, exc):
        # Pydantic's default error includes submitted values, including passwords.
        return JSONResponse(status_code=422, content={'detail': [
            {'type': error['type'], 'loc': error['loc'], 'msg': 'Campo inválido.'}
            for error in exc.errors()]})

    @api.exception_handler(SetupError)
    async def setup_error(request, exc):
        return JSONResponse(status_code=exc.status, content={'detail': exc.code})

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
        return {'product':'NOVA Server','version':'0.3.0-dev',
                'owner_setup_required':not store.has_admin(),
                'remote_access_enabled':False,
                'directory_enabled':directory_control is not None,
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
            with PASSWORD_SLOTS:
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
        attempt = store.reserve_login_attempt(ip)
        if attempt is None:
            raise HTTPException(429,'Demasiadas tentativas; aguarda 15 minutos.', headers={'Retry-After':'900'})
        admin=store.get_admin(payload.username)
        with PASSWORD_SLOTS:
            valid = verify_password(admin[1] if admin is not None else DUMMY_HASH, payload.password)
        if not valid or admin is None:
            raise HTTPException(401,'Credenciais inválidas.')
        store.complete_successful_login(attempt)
        token=new_session_token()
        store.save_session(token,lifetime=3600)
        return {'access_token':token,'token_type':'bearer','expires_in':3600}

    @api.post('/api/v1/admin/logout')
    def logout(token:str=Depends(owner)):
        store.revoke_session(token)
        return {'ok':True}

    @api.get('/api/v1/admin/overview')
    async def overview(token:str=Depends(owner)):
        result=await probe_jellyfin(jellyfin_url, expected_server_id=jellyfin_server_id)
        return {'nova_core':'running','jellyfin':result,
                'library_roots':[{'name':name, 'container_path':'/media/'+name,
                                  'configured_read_only':True, 'verification':'not_checked',
                                  'readable':None, 'read_only':None, 'indexed':None}
                                 for name in ('source-a', 'source-b')],
                'connect':{'state':'disabled','reason':'P03 pending secure remote design'},
                'directory':{'state':'configured' if directory_control else 'disabled'},
                'admin_interface':{'exposure':getattr(api.state,'admin_exposure','loopback_only_required')}}

    @api.post('/api/v1/admin/directory/accounts',status_code=201)
    def directory_account(payload:DirectoryNewAccount,token:str=Depends(owner)):
        if directory_control is None:raise HTTPException(503,'directory_not_configured')
        devices.limit('owner.directory.accounts','owner',10,10)
        from .directory_control import safe_operation,ControlError
        try:return safe_operation(lambda:directory_control.create_account(payload.username,payload.password,
                                                                          payload.member_username,payload.member_password))
        except ControlError as error:raise HTTPException(error.status,error.code) from None

    @api.get('/api/v1/admin/connect')
    def connect_settings(token:str=Depends(owner)):
        return {'schema_version':1, 'active_provider':None, 'remote_access_enabled':False,
                'providers':provider_catalog(), 'drafts':store.connect_drafts()}

    @api.get('/api/v1/admin/connect/tailscale')
    def tailscale_status(token:str=Depends(owner)):
        if tailscale_control is None:
            return {'state':'not_prepared','profile_approved':False,'gateway_verified':False,'remote_access_enabled':False}
        return tailscale_control.status()

    @api.post('/api/v1/admin/connect/tailscale')
    def tailscale_decision(payload:TailscaleDecision,token:str=Depends(owner)):
        devices.limit('owner.tailscale','owner',30,30,60)
        if tailscale_control is None:raise DeviceError('tailscale_policy_not_prepared',409)
        return tailscale_control.decide(payload.revision,payload.approve,payload.policy_digest)

    @api.get('/api/v1/admin/connect/wireguard/enrollments')
    def wireguard_enrollments(token:str=Depends(owner)):
        return {'enrollments':WireGuardEnrollments(store).list(), 'remote_access_enabled':False}

    @api.get('/api/v1/admin/connect/wireguard/plan')
    def wireguard_plan(token:str=Depends(owner)):
        return WireGuardEnrollments(store).gateway_plan()

    @api.get('/api/v1/admin/connect/wireguard/gateway')
    def wireguard_gateway_status(token:str=Depends(owner)):
        if gateway_publisher is None:
            return {'state':'disabled', 'configuration_observed':False, 'handshake_verified':False,
                    'remote_access_enabled':False, 'peers':[]}
        return gateway_publisher.status()

    @api.post('/api/v1/admin/connect/wireguard/enrollments/{device_id}')
    def wireguard_decision(device_id:str, payload:EnrollmentDecision, token:str=Depends(owner)):
        devices.limit('owner.wireguard', 'owner', 60, 60, 60)
        return WireGuardEnrollments(store).decide(device_id, payload.revision, payload.approve)

    @api.get('/api/v1/admin/lan')
    def lan_settings(token:str=Depends(owner)):
        if not hasattr(api.state,'lan_configuration'):raise HTTPException(404,'lan_not_configured')
        return api.state.lan_configuration

    @api.get('/api/v1/admin/setup')
    def setup_status(token:str=Depends(owner)):
        return store.setup_state()

    def directory_call(action, *, limited=True):
        if directory_control is None:
            raise HTTPException(503, 'directory_not_configured')
        if limited:
            devices.limit('owner.directory', 'owner', 10, 10)
        try:
            return safe_operation(lambda: action(directory_control))
        except ControlError as error:
            raise HTTPException(error.status, error.code) from None

    @api.get('/api/v1/admin/directory')
    def directory_status(token:str=Depends(owner)):
        if directory_control is None:
            return {'enabled':False, 'state':'disabled', 'media_authorized':False}
        return directory_call(lambda control: control.status(), limited=False)

    @api.post('/api/v1/admin/directory/identity')
    def directory_identity(token:str=Depends(owner)):
        return directory_call(lambda control: control.initialize())

    @api.post('/api/v1/admin/directory/publish')
    def directory_publish(payload:DirectoryPublication, token:str=Depends(owner)):
        return directory_call(lambda control: control.operate('publish', payload.username, payload.password, payload.name))

    @api.post('/api/v1/admin/directory/check')
    def directory_check(payload:DirectoryCredentials, token:str=Depends(owner)):
        return directory_call(lambda control: control.operate('check', payload.username, payload.password))

    @api.post('/api/v1/admin/directory/renew')
    def directory_renew(token:str=Depends(owner)):
        return directory_call(lambda control:control.renew_if_due(force=True))

    @api.post('/api/v1/admin/setup/jellyfin')
    async def setup_jellyfin(payload:SetupRequest, token:str=Depends(owner)):
        return await api.state.jellyfin_setup.run(payload, configure=True)

    @api.post('/api/v1/admin/setup/jellyfin/verify')
    async def verify_jellyfin(payload:Credentials, token:str=Depends(owner)):
        return await api.state.jellyfin_setup.run(payload)

    @api.put('/api/v1/admin/connect/draft')
    def save_connect_draft(payload:ConnectDraft, token:str=Depends(owner)):
        store.save_connect_draft(payload.model_dump())
        return {'saved':True, 'state':'draft', 'provider':payload.provider,
                'remote_access_enabled':False}

    @api.get('/',response_class=HTMLResponse)
    def home():
        return (Path(__file__).parent/'static'/'index.html').read_text(encoding='utf-8')

    @api.post('/api/v1/admin/devices/inspect')
    def inspect_device(payload:UserCode, token:str=Depends(owner)):
        devices.limit('owner.inspect', 'owner', 20, 20)
        return devices.inspect(payload.user_code)

    @api.post('/api/v1/admin/devices/decision')
    def decide_device(payload:DeviceDecision, token:str=Depends(owner)):
        devices.limit('owner.decision', 'owner', 20, 20)
        return devices.decide(payload.user_code, payload.request_id, payload.approve)

    @api.get('/api/v1/admin/devices')
    def list_devices(token:str=Depends(owner)):
        return {'server_id': devices.identity(), 'devices': devices.list()}

    @api.get('/api/v1/admin/members')
    def list_members(token:str=Depends(owner)):
        from .members import Members
        return {'members':Members(store,jellyfin_url).list()}

    @api.post('/api/v1/admin/members')
    async def configure_member(payload:MemberConfiguration,token:str=Depends(owner)):
        from .members import Members
        devices.limit('owner.members','owner',10,10)
        return await Members(store,jellyfin_url).configure(payload)

    @api.delete('/api/v1/admin/members/{subject}')
    def revoke_member(subject:str,token:str=Depends(owner)):
        from .members import Members
        return Members(store,jellyfin_url).revoke(subject)

    @api.delete('/api/v1/admin/devices/{device_id}')
    def revoke_device(device_id:str, token:str=Depends(owner)):
        return devices.revoke(device_id)

    api.mount('/static',StaticFiles(directory=str(Path(__file__).parent/'static')),name='static')
    return api

app=make_app()
