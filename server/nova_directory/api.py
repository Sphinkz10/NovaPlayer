"""Explicit opt-in HTTPS Directory, separate from local owner administration."""
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from nova_server.client_api import SmallBody
from nova_server.device_api import Payload, invalid_device_payload, device_error
from .protocol import USERNAME, ChallengeRequest, Proof, private_origin
from .store import Registry, DirectoryError


class Login(Payload):
    username: str = Field(min_length=3, max_length=40, pattern=USERNAME)
    password: str = Field(min_length=1, max_length=1024)


class Membership(Payload):
    username: str = Field(pattern=USERNAME)
    allowed: bool = Field(strict=True)


def make_directory(state, origin):
    private_origin(origin)
    registry = Registry(state, origin)
    app = FastAPI(title='NOVA Directory laboratory', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.registry = registry
    app.add_exception_handler(DirectoryError, device_error)
    app.add_exception_handler(RequestValidationError, invalid_device_payload)
    app.add_middleware(SmallBody, maximum=8192)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(origin).hostname], www_redirect=False)

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

    @app.get('/api/v1/directory/health')
    def health():
        return {'status':'up','component':'nova-directory','laboratory':True}

    @app.post('/api/v1/directory/login')
    def login(payload: Login, request: Request):
        return registry.login(payload.username, payload.password, request.client.host if request.client else 'unknown')

    @app.post('/api/v1/directory/logout')
    def logout(auth=Depends(identity)):
        registry.logout(auth[1]); return {'logged_out':True}

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
