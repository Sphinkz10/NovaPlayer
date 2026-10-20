"""Small, authenticated media surface. No arbitrary URLs, paths or Jellyfin proxy."""
from contextlib import asynccontextmanager
import re
import time

import httpx
from cryptography.exceptions import InvalidTag
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .devices import Devices, DeviceError
from .members import Members
from .setup import SetupError

ID = re.compile(r'^[a-f0-9]{32}$')
TYPES = {'Movie', 'Episode'}


def media_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise DeviceError('unknown_media', 404)
    return value


def text(value, maximum):
    return ''.join(c for c in value if c.isprintable())[:maximum] if isinstance(value, str) else ''


def number(value, maximum=10**16):
    return value if type(value) is int and 0 <= value <= maximum else 0


class PlaybackEvent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    event: str = Field(pattern=r'^(start|progress|stop)$')
    position_ticks: int = Field(ge=0, le=10**16)
    paused: bool = False


class Media:
    def __init__(self, members: Members):
        self.members = members
        self.store = members.store

    @asynccontextmanager
    async def session(self, access, library, active_transfer=False):
        media_id(library)
        grant = await self.members.authorization(access)
        if library not in {lib['id'] for lib in grant['libraries']}:
            raise DeviceError('unknown_library', 404)
        subject = grant['account_id']
        with self.store._db() as db:
            row = db.execute('SELECT jellyfin_user,server_id,credential FROM member_accounts '
                             'WHERE subject=? AND disabled=0 AND revision=?', (subject, grant['revision'])).fetchone()
        if not row or not row[2]:
            raise DeviceError('member_permissions_changed', 403)
        credential = self.members.vault.open(row[2], 'member:'+subject+':'+row[1])
        headers = self.members._headers(subject)
        headers['Authorization'] += ', Token="'+credential+'"'

        def guard():
            if not active_transfer:
                Devices(self.store).authenticate(access)
            with self.store._db() as db:
                if active_transfer and not db.execute('SELECT 1 FROM devices WHERE id=? AND account_id=? '
                    'AND revoked=0 AND expires_at>?', (grant['device_id'],subject,int(time.time()))).fetchone():
                    raise DeviceError('invalid_token', 401)
                if not db.execute('SELECT 1 FROM member_accounts WHERE subject=? AND disabled=0 AND revision=?',
                                  (subject, grant['revision'])).fetchone():
                    raise DeviceError('member_permissions_changed', 403)

        async with self.members._client(headers) as client:
            yield client, row[0], grant, guard
            guard()  # Discard buffered data if authorization changed during upstream I/O.

    async def query(self, client, uid, library, **params):
        return await self.members.setup._request(client, 'GET', '/Items', params={
            'UserId': uid, 'ParentId': library, 'Recursive': 'true', 'IncludeItemTypes': 'Movie,Episode',
            'Fields': 'Overview,MediaSources,MediaStreams', 'EnableUserData': 'true',
            'EnableImages': 'false', 'SortBy': 'SortName', 'SortOrder': 'Ascending', **params})

    @staticmethod
    def clean(item):
        if not isinstance(item, dict) or item.get('Type') not in TYPES:
            raise SetupError('jellyfin_invalid_media')
        user = item.get('UserData') or {}
        return {'id': media_id(item.get('Id')), 'name': text(item.get('Name'), 200),
                'type': item['Type'], 'series': text(item.get('SeriesName'), 200),
                'season': number(item.get('ParentIndexNumber'), 10000),
                'episode': number(item.get('IndexNumber'), 100000),
                'year': number(item.get('ProductionYear'), 9999),
                'overview': text(item.get('Overview'), 4000),
                'runtime_ticks': number(item.get('RunTimeTicks')),
                'position_ticks': number(user.get('PlaybackPositionTicks')),
                'played': user.get('Played') is True}

    async def item(self, client, uid, library, item):
        media_id(item)
        # IDs alone are insufficient: require membership under the selected permitted root.
        try:
            data = await self.query(client, uid, library, Ids=item, Limit=1)
        except SetupError as error:
            # Jellyfin may return 401/403 rather than an empty list for a foreign
            # item. The account/policy were already checked; hide item existence.
            if error.code == 'jellyfin_credentials_rejected':
                raise DeviceError('unknown_media', 404) from None
            raise
        if not isinstance(data, dict) or not isinstance(data.get('Items'), list):
            raise SetupError('jellyfin_invalid_media')
        found = data['Items']
        if len(found) != 1 or found[0].get('Id', '').replace('-', '') != item:
            raise DeviceError('unknown_media', 404)
        self.clean(found[0])
        return found[0]

    async def catalog(self, access, library, start=0, search='', kind='all'):
        if type(start) is not int or not 0 <= start <= 100000 or len(search) > 100 or any(ord(c)<32 for c in search):
            raise DeviceError('invalid_catalog_query', 422)
        if kind not in ('all', 'movies', 'episodes'):
            raise DeviceError('invalid_catalog_query', 422)
        async with self.session(access, library) as (client, uid, grant, guard):
            data = await self.query(client, uid, library, StartIndex=start, Limit=24, SearchTerm=search,
                                    IncludeItemTypes={'all':'Movie,Episode','movies':'Movie','episodes':'Episode'}[kind])
            if not isinstance(data, dict) or not isinstance(data.get('Items'), list) or len(data['Items']) > 24:
                raise SetupError('jellyfin_invalid_media')
            total = number(data.get('TotalRecordCount'), 1000000)
            return {'server_id': grant['server_id'], 'account_id': grant['account_id'], 'library_id': library,
                    'items': [self.clean(item) for item in data['Items']], 'start': start, 'total': total,
                    'next': start+24 if start+24 < total and len(data['Items']) == 24 else None}

    async def detail(self, access, library, item):
        async with self.session(access, library) as (client, uid, grant, guard):
            raw = await self.item(client, uid, library, item)
            return {'server_id': grant['server_id'], 'account_id': grant['account_id'],
                    'library_id': library, 'item': self.clean(raw), 'method': 'DirectPlay',
                    'stream_path': '/api/v1/media/libraries/'+library+'/items/'+item+'/stream'}

    async def event(self, access, library, item, payload):
        async with self.session(access, library) as (client, uid, grant, guard):
            raw = await self.item(client, uid, library, item)
            runtime = number(raw.get('RunTimeTicks'))
            if runtime and payload.position_ticks > runtime:
                raise DeviceError('invalid_playback_position', 422)
            path = {'start':'', 'progress':'/Progress', 'stop':'/Stopped'}[payload.event]
            body = {'ItemId': item, 'PositionTicks': payload.position_ticks,
                    'IsPaused': payload.paused, 'PlayMethod': 'DirectPlay', 'CanSeek': True}
            guard()
            await self.members.setup._request(client, 'POST', '/Sessions/Playing'+path, json=body)
            return {'recorded': True}

    async def stream(self, access, library, item, range_header=None):
        if range_header is not None:
            match = re.fullmatch(r'bytes=(\d{1,16})-(\d{1,16})?', range_header)
            if not match or (match[2] is not None and int(match[2]) < int(match[1])):
                raise DeviceError('invalid_range', 416)
        # Access must be valid at open. A token rotation must not cut an existing
        # authenticated file response; device/account revocation and lease expiry still do.
        context = self.session(access, library, active_transfer=True)
        client = response = None
        try:
            client, uid, grant, guard = await context.__aenter__()
            raw = await self.item(client, uid, library, item)
            sources = raw.get('MediaSources') or []
            source = next((s for s in sources if s.get('Protocol') == 'File' and
                           s.get('IsRemote') is not True and ID.fullmatch(s.get('Id', ''))), None)
            if source is None:
                raise DeviceError('direct_play_unavailable', 409)
            headers = {'Range': range_header} if range_header else {}
            request = client.build_request('GET', '/Videos/'+item+'/stream',
                params={'Static':'true', 'MediaSourceId':source['Id'], 'UserId':uid}, headers=headers)
            response = await client.send(request, stream=True)
            if response.status_code == 416:
                raise DeviceError('invalid_range', 416)
            if response.status_code not in (200, 206) or response.headers.get('Content-Encoding', 'identity') != 'identity':
                raise DeviceError('media_unavailable', 502)
            mime = response.headers.get('Content-Type', '').split(';')[0].lower()
            if mime not in ('video/mp4','video/x-matroska','video/webm','application/octet-stream','video/x-m4v'):
                raise DeviceError('unsupported_media', 415)
            size = response.headers.get('Content-Length', '')
            if not size.isdecimal() or not 0 < int(size) <= 10**13:
                raise DeviceError('media_unavailable', 502)
            outgoing = {'Content-Length':size, 'Accept-Ranges':'bytes'}
            if response.status_code == 206:
                value = response.headers.get('Content-Range', '')
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', value)
                if (not range_header or not match or int(match[2])-int(match[1])+1 != int(size) or
                        int(match[3]) <= int(match[2]) or int(match[1]) != int(range_header[6:].split('-')[0]) or
                        (range_header.split('-')[1] and int(match[2]) > int(range_header.split('-')[1]))):
                    raise DeviceError('media_unavailable', 502)
                outgoing['Content-Range'] = value
            elif range_header:
                raise DeviceError('range_not_supported', 502)
            guard()
        except BaseException:
            if response is not None: await response.aclose()
            if client is not None: await context.__aexit__(None, None, None)
            raise

        async def body():
            remaining = int(size)
            try:
                async for chunk in response.aiter_bytes(chunk_size=64*1024):
                    guard()  # Revocation/expiry applies to active transfers as well as new requests.
                    if len(chunk) > remaining:
                        raise DeviceError('media_length_changed', 502)
                    remaining -= len(chunk)
                    yield chunk
                if remaining:
                    raise DeviceError('media_interrupted', 502)
            finally:
                await response.aclose()
                await context.__aexit__(None, None, None)
        return StreamingResponse(body(), status_code=response.status_code, media_type=mime, headers=outgoing)


def mount_media(api, store, base_url):
    def service():
        return Media(Members(store, base_url))

    def access(request):
        source = request.client.host if request.client else 'unknown'
        Devices(store).limit('media', source, 120, 600, 60)
        bearer = request.headers.get('Authorization', '')
        if not bearer.startswith('Bearer ') or not 40 <= len(bearer[7:]) <= 128:
            raise DeviceError('invalid_token', 401)
        return bearer[7:]

    async def safely(operation):
        try:
            return await operation
        except (SetupError, httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError, OSError, InvalidTag):
            raise DeviceError('media_unavailable', 503) from None

    from fastapi import Request

    @api.get('/api/v1/media/libraries/{library}/items')
    async def catalog(library: str, request: Request, start: int = 0, search: str = '', kind: str = 'all'):
        return await safely(service().catalog(access(request), library, start, search, kind))

    @api.get('/api/v1/media/libraries/{library}/items/{item}')
    async def detail(library: str, item: str, request: Request):
        return await safely(service().detail(access(request), library, item))

    @api.get('/api/v1/media/libraries/{library}/items/{item}/stream')
    async def stream(library: str, item: str, request: Request):
        return await safely(service().stream(access(request), library, item, request.headers.get('Range')))

    @api.post('/api/v1/media/libraries/{library}/items/{item}/events')
    async def event(library: str, item: str, payload: PlaybackEvent, request: Request):
        return await safely(service().event(access(request), library, item, payload))
