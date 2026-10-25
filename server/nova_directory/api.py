"""Explicit opt-in HTTPS Directory, separate from local owner administration."""
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from nova_server.client_api import SmallBody
from nova_server.device_api import Payload, invalid_device_payload, device_error
from .protocol import ID, USERNAME, Descriptor, ChallengeRequest, Proof, private_origin
from .store import Registry, DirectoryError


class Login(Payload):
    username: str = Field(min_length=3, max_length=40, pattern=USERNAME)
    password: str = Field(min_length=1, max_length=1024)


class Membership(Payload):
    username: str = Field(pattern=USERNAME)
    allowed: bool = Field(strict=True)


class AssertionRequest(Payload):
    entry_id: str = Field(pattern=ID)


def make_directory(state, origin, *, operator_id=None, bootstrap_profile=None):
    private_origin(origin)
    registry = Registry(state, origin)
    app = FastAPI(title='NOVA Directory laboratory', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.registry = registry
    app.add_exception_handler(DirectoryError, device_error)
    app.add_exception_handler(RequestValidationError, invalid_device_payload)
    app.add_middleware(SmallBody, maximum=8192)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(origin).hostname], www_redirect=False)

    if bootstrap_profile is not None:
        import json
        from pathlib import Path
        profile_path=Path(bootstrap_profile)
        if profile_path.stat().st_size>16384:raise ValueError('Bootstrap too large')
        profile=json.loads(profile_path.read_text(encoding='utf8'))
        if (set(profile)!={'version','purpose','origin','certificate_pem','public_key'} or profile['version']!=1 or
                profile['purpose']!='nova-directory-bootstrap' or profile['origin']!=origin or
                profile['public_key']!=registry.identity_public):raise ValueError('Bootstrap identity mismatch')
        Descriptor(server_id='00000000-0000-4000-8000-000000000001',name='Directory',client_origin=origin,
                   certificate_pem=profile['certificate_pem']).check_certificate(__import__('time').time())
        @app.get('/api/v1/directory/bootstrap')
        def bootstrap():return profile

    if operator_id is not None:
        import re
        if not re.fullmatch(ID,operator_id):raise ValueError('Invalid Directory operator')
        with registry.db() as db:
            if not db.execute('SELECT 1 FROM accounts WHERE id=? AND disabled=0',(operator_id,)).fetchone():
                raise ValueError('Directory operator missing')

    @app.middleware('http')
    async def boundary(request, call_next):
        if request.url.scheme != 'https':
            response = JSONResponse({'error':'https_required'}, status_code=400)
        else:
            try:
                registry.limit('request', request.client.host if request.client else 'unknown', 120, 600)
                response = await call_next(request)
            except DirectoryError as error:
                response = await device_error(request, error)
        response.headers.update({'Cache-Control':'no-store', 'Pragma':'no-cache',
            'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'"})
        return response

    def identity(request: Request):
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer ') or not 40 <= len(header[7:]) <= 128:
            raise DirectoryError('invalid_session', 401)
        return registry.authenticate(header[7:]), header[7:]

    def renewal_token(request:Request):
        header=request.headers.get('Authorization','')
        if not header.startswith('Bearer ') or not 40<=len(header[7:])<=128:
            raise DirectoryError('invalid_renewal_credential',401)
        return header[7:]

    @app.get('/api/v1/directory/health')
    def health():
        return {'status':'up','component':'nova-directory','laboratory':True}

    @app.get('/api/v1/directory/identity')
    def issuer():
        return {'issuer':origin,'public_key':registry.identity_public,'purpose':'associate-v1'}

    @app.post('/api/v1/directory/assertions')
    def assertion(payload:AssertionRequest,auth=Depends(identity)):
        return registry.assertion(auth[0],payload.entry_id)

    @app.post('/api/v1/directory/servers/{entry}/renewal-credential')
    def create_renewal_credential(entry:str,auth=Depends(identity)):
        return registry.renewal_credential(auth[0],entry)

    @app.post('/api/v1/directory/renewals/challenges',status_code=201)
    def renewal_challenge(payload:Descriptor,request:Request):
        return registry.agent_challenge(renewal_token(request),payload)

    @app.post('/api/v1/directory/renewals/registrations',status_code=201)
    def renewal_register(payload:Proof,request:Request):
        return registry.agent_register(renewal_token(request),payload)

    @app.post('/api/v1/directory/login')
    def login(payload: Login, request: Request):
        return registry.login(payload.username, payload.password, request.client.host if request.client else 'unknown')

    @app.post('/api/v1/directory/logout')
    def logout(auth=Depends(identity)):
        registry.logout(auth[1]); return {'logged_out':True}

    if operator_id is not None:
        class CreateAccount(Payload):
            username:str=Field(pattern=USERNAME)
            password:str=Field(min_length=14,max_length=1024)
            entry_id:str=Field(pattern=ID)

        @app.post('/api/v1/directory/operator/accounts',status_code=201)
        def operator_create(payload:CreateAccount,auth=Depends(identity)):
            if auth[0]!=operator_id:raise DirectoryError('operator_required',403)
            with registry.db() as db:
                if not db.execute('SELECT 1 FROM entries WHERE id=? AND owner_id=? AND disabled=0',
                                  (payload.entry_id,operator_id)).fetchone():raise DirectoryError('unknown_entry',404)
            created=registry.create_account(payload.username,payload.password,share_entry=payload.entry_id,owner=operator_id)
            return {'account_id':created,'username':payload.username,'discovery_allowed':True,'media_authorized':False}

    @app.post('/api/v1/directory/challenges', status_code=201)
    def challenge(payload: ChallengeRequest, auth=Depends(identity)):
        return registry.challenge(auth[0], payload)

    @app.post('/api/v1/directory/registrations', status_code=201)
    def register(payload: Proof, auth=Depends(identity)):
        return registry.register(auth[0], payload)

    @app.get('/api/v1/directory/servers')
    def servers(auth=Depends(identity)):
        return {'servers':registry.discover(auth[0]), 'media_authorized':False}

    @app.put('/api/v1/directory/servers/{entry}/members')
    def membership(entry: str, payload: Membership, auth=Depends(identity)):
        registry.membership(auth[0], entry, payload.username, payload.allowed)
        return {'discovery_allowed':payload.allowed,'media_authorized':False}

    @app.delete('/api/v1/directory/servers/{entry}')
    def remove(entry: str, auth=Depends(identity)):
        registry.remove(auth[0], entry); return {'removed':True}

    return app
