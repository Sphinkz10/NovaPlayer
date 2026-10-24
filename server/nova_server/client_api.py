"""Separate HTTPS device/media surface. Administration is never mounted here."""
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
from .wireguard import Enrollment, WireGuardEnrollments


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


def make_client_app(state_dir=None, origin=None, *, require_directory=False, wireguard_profiles=None, tailscale_profiles=None):
    origin, host = client_origin(origin or os.environ.get('NOVA_CLIENT_ORIGIN', ''))
    store = Store(state_dir or os.environ.get('NOVA_STATE_DIR', '/data'))
    devices = Devices(store)
    if wireguard_profiles is None and os.environ.get('NOVA_WIREGUARD_PUBLIC_CONFIG'):
        from .wireguard_profile import WireGuardProfiles
        wireguard_profiles = WireGuardProfiles.local(store,os.environ['NOVA_WIREGUARD_PUBLIC_CONFIG'])
    remote_origin = wireguard_profiles.origin if wireguard_profiles is not None else None
    if tailscale_profiles is None and os.environ.get('NOVA_TAILSCALE_PUBLIC_CONFIG'):
        from .tailscale_profile import TailscaleProfiles
        tailscale_profiles=TailscaleProfiles.local(store,os.environ['NOVA_TAILSCALE_PUBLIC_CONFIG'],origin)
    from .tailscale_control import TailscaleControl
    tailscale_options=TailscaleControl.options()
    if tailscale_options:
        if tailscale_profiles is None:raise ValueError('Prepared Tailscale policy required')
        if origin!=tailscale_options['base_origin']:raise ValueError('Tailscale base origin mismatch')
        tailscale_profiles.approval=TailscaleControl.local(store,**tailscale_options)
    remote_origins=[value for value in (remote_origin,tailscale_profiles.origin if tailscale_profiles else None) if value]
    if len(remote_origins)!=len(set(urlsplit(value).hostname for value in remote_origins)):
        raise ValueError('Remote providers require distinct gateway addresses')
    api = FastAPI(title='NOVA device laboratory', docs_url=None, redoc_url=None, openapi_url=None)
    api.state.devices = devices
    def media_transport_guard(request):
        if (tailscale_profiles and tailscale_profiles.approval and
                request.url.hostname==urlsplit(tailscale_profiles.origin).hostname):
            tailscale_profiles.approval.authorization()
    api.state.media_transport_guard=media_transport_guard
    api.add_exception_handler(DeviceError, device_error)
    api.add_exception_handler(RequestValidationError, invalid_device_payload)
    api.add_middleware(SmallBody)
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=[host]+[urlsplit(value).hostname for value in remote_origins], www_redirect=False)

    def tailscale_approved():
        try:return tailscale_profiles.approval.status()['profile_approved']
        except DeviceError:return False

    @api.middleware('http')
    async def transport(request: Request, call_next):
        if request.url.scheme != 'https':
            response = JSONResponse({'error': 'https_required'}, status_code=400)
        elif (tailscale_profiles and tailscale_profiles.approval and
                request.url.hostname==urlsplit(tailscale_profiles.origin).hostname and
                not tailscale_approved()):
            response=JSONResponse({'error':'tailscale_owner_approval_required'},status_code=403)
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
        elif require_directory or (store.dir/'directory-control.sqlite3').exists():
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
                                'client_origin': next((value for value in remote_origins if request.url.hostname==urlsplit(value).hostname),origin),
                                'media_enabled': result['account_id'] is not None,
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
        return {'authorized':True,'server_id':result['server_id'],'library':permitted[0],'media_enabled':True}

    @api.post('/api/v1/device/logout')
    def logout(request: Request):
        limit(request, 'logout')
        bearer = request.headers.get('Authorization', '')
        if not bearer.startswith('Bearer ') or not 40 <= len(bearer[7:]) <= 128:
            raise DeviceError('invalid_token', 401)
        device = devices.authenticate(bearer[7:])
        return devices.revoke(device['device_id'])

    def wireguard_access(request):
        limit(request, 'wireguard', 20, 100, 60)
        bearer = request.headers.get('Authorization', '')
        if not bearer.startswith('Bearer ') or not 40 <= len(bearer[7:]) <= 128:
            raise DeviceError('invalid_token', 401)
        return bearer[7:]

    @api.post('/api/v1/device/wireguard')
    def enroll_wireguard(payload: Enrollment, request: Request):
        return WireGuardEnrollments(store).request(wireguard_access(request), payload.public_key)

    @api.get('/api/v1/device/wireguard')
    def wireguard_status(request: Request):
        return WireGuardEnrollments(store).status(wireguard_access(request))

    @api.get('/api/v1/device/wireguard/profile')
    def wireguard_profile(request: Request):
        access = wireguard_access(request)
        devices.authenticate(access)
        if wireguard_profiles is None:
            raise DeviceError('wireguard_gateway_unavailable',503)
        return wireguard_profiles.issue(access)

    @api.get('/api/v1/device/tailscale/profile')
    def tailscale_profile(request:Request):
        limit(request,'tailscale',20,100,60)
        bearer=request.headers.get('Authorization','')
        if not bearer.startswith('Bearer ') or not 40<=len(bearer[7:])<=128:
            raise DeviceError('invalid_token',401)
        devices.authenticate(bearer[7:])
        if tailscale_profiles is None:raise DeviceError('tailscale_gateway_unavailable',503)
        return tailscale_profiles.issue(bearer[7:])

    from .media import mount_media
    mount_media(api,store,os.environ.get('NOVA_JELLYFIN_URL','http://jellyfin:8096'))
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
