"""Separate HTTPS-only device surface. Does not mount NOVA Control or Jellyfin."""
import ipaddress
import os
import re
import ssl
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .storage import Store
from .devices import Devices, DeviceError
from .device_api import StartDevice, DeviceCode, RefreshDevice, device_error, invalid_device_payload


def client_origin(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment
                or parsed.netloc.endswith(':') or any(c.isspace() for c in url)):
            raise ValueError()
        host = parsed.hostname
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r'[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?', host):
                raise ValueError()
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError()
    except (ValueError, AttributeError):
        raise ValueError('NOVA_CLIENT_ORIGIN requires an explicit HTTPS origin without credentials or paths.') from None
    return url.rstrip('/'), host


class SmallBody:
    """Bound streamed JSON before parsing, including absent/incorrect Content-Length."""
    def __init__(self, app, maximum=4096):
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > self.maximum:
                return await JSONResponse({'error': 'request_too_large'}, status_code=413,
                                          headers={'Cache-Control': 'no-store'})(scope, receive, send)
            chunks.append(message.get('body', b''))
            if not message.get('more_body'):
                break
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)


def make_client_app(state_dir=None, origin=None):
    origin, host = client_origin(origin or os.environ.get('NOVA_CLIENT_ORIGIN', ''))
    store = Store(state_dir or os.environ.get('NOVA_STATE_DIR', '/data'))
    devices = Devices(store)
    api = FastAPI(title='NOVA device laboratory', docs_url=None, redoc_url=None, openapi_url=None)
    api.state.devices = devices
    api.add_exception_handler(DeviceError, device_error)
    api.add_exception_handler(RequestValidationError, invalid_device_payload)
    api.add_middleware(SmallBody)
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=[host], www_redirect=False)

    @api.middleware('http')
    async def transport(request: Request, call_next):
        if request.url.scheme != 'https':
            response = JSONResponse({'error': 'https_required'}, status_code=400)
        else:
            response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Pragma'] = 'no-cache'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'none'"
        return response

    def limit(request, action, maximum=60, total=240, window=60):
        source = request.client.host if request.client else 'unknown'
        devices.limit(action, source, maximum, total, window)

    @api.post('/api/v1/device/authorize', status_code=201)
    def authorize(payload: StartDevice, request: Request):
        limit(request, 'authorize', 10, 64, 600)
        identity=None
        if payload.assertion is not None:
            from .directory_proof import verify_device_assertion
            identity=verify_device_assertion(store.dir,devices.identity(),payload.assertion)
        elif (store.dir/'directory-control.sqlite3').exists():
            raise DeviceError('directory_identity_required',403)
        return devices.start(payload.label,identity)

    @api.post('/api/v1/device/token')
    def token(payload: DeviceCode, request: Request):
        limit(request, 'poll')
        return devices.poll(payload.device_code)

    @api.post('/api/v1/device/refresh')
    def refresh(payload: RefreshDevice, request: Request):
        limit(request, 'refresh')
        return devices.refresh(payload.refresh_token)

    @api.get('/api/v1/device/me')
    def me(request: Request):
        limit(request, 'me')
        bearer = request.headers.get('Authorization', '')
        if not bearer.startswith('Bearer ') or not 40 <= len(bearer[7:]) <= 128:
            raise DeviceError('invalid_token', 401)
        result = devices.authenticate(bearer[7:])
        result['descriptor'] = {'schema_version': 1, 'server_id': result['server_id'],
                                'client_origin': origin, 'media_enabled': False,
                                'directory_enabled': result['account_id'] is not None, 'remote_access_enabled': False}
        return result

    @api.get('/api/v1/device/libraries')
    async def libraries(request:Request):
        limit(request,'libraries')
        bearer=request.headers.get('Authorization','')
        if not bearer.startswith('Bearer ') or not 40<=len(bearer[7:])<=128:
            raise DeviceError('invalid_token',401)
        from .members import Members
        from .setup import SetupError
        try:
            return await Members(store,os.environ.get('NOVA_JELLYFIN_URL','http://jellyfin:8096')).authorization(bearer[7:])
        except SetupError:
            raise DeviceError('member_authorization_unavailable',503) from None

    @api.get('/api/v1/device/libraries/{library_id}/authorization')
    async def library_authorization(library_id:str,request:Request):
        result=await libraries(request)
        permitted=[lib for lib in result['libraries'] if lib['id']==library_id]
        if not permitted:raise DeviceError('unknown_library',404)
        return {'authorized':True,'server_id':result['server_id'],'library':permitted[0],'media_enabled':False}

    @api.post('/api/v1/device/logout')
    def logout(request: Request):
        limit(request, 'logout')
        bearer = request.headers.get('Authorization', '')
        if not bearer.startswith('Bearer ') or not 40 <= len(bearer[7:]) <= 128:
            raise DeviceError('invalid_token', 401)
        device = devices.authenticate(bearer[7:])
        return devices.revoke(device['device_id'])

    return api


def main():
    """Explicit opt-in process; Compose M2 does not start/expose this service."""
    import uvicorn
    origin, _ = client_origin(os.environ.get('NOVA_CLIENT_ORIGIN', ''))
    cert = Path(os.environ['NOVA_CLIENT_CERT']).resolve(strict=True)
    key = Path(os.environ['NOVA_CLIENT_KEY']).resolve(strict=True)
    # Validate the certificate/key pair before starting; never fall back to HTTP.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    uvicorn.run(make_client_app(origin=origin), host='127.0.0.1',
                port=urlsplit(origin).port or 443, ssl_certfile=str(cert), ssl_keyfile=str(key),
                proxy_headers=False, access_log=False)


if __name__ == '__main__':
    main()
