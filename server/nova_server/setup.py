"""Resumable owner-only Jellyfin setup. Credentials live only for this request."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class SetupError(Exception):
    def __init__(self, code, status=502):
        self.code, self.status = code, status
        super().__init__(code)


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=40)
    password: SecretStr = Field(min_length=1, max_length=1024)


class Library(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80, pattern=r'^[\w .()-]+$')
    collection_type: Literal['movies', 'tvshows'] = 'movies'
    roots: list[Literal['source-a', 'source-b']] = Field(min_length=1, max_length=2)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        if value != value.strip() or value in ('.', '..'):
            raise ValueError('Invalid library name')
        return value


class SetupRequest(Credentials):
    server_name: str = Field(default='NOVA', min_length=1, max_length=80)
    libraries: list[Library] = Field(min_length=1, max_length=2)

    @model_validator(mode='after')
    def unique_roots(self):
        roots = [root for lib in self.libraries for root in lib.roots]
        if sorted(roots) != ['source-a', 'source-b']:
            raise ValueError('Each configured source must occur exactly once')
        names = [lib.name.casefold() for lib in self.libraries]
        if len(set(names)) != len(names):
            raise ValueError('Library names must be unique')
        return self


class JellyfinSetup:
    def __init__(self, store, base_url, expected_id=None, transport=None):
        self.store, self.base_url = store, base_url.rstrip('/')
        self.expected_id, self.transport = expected_id, transport

    async def run(self, payload: Credentials, *, configure=False):
        lease = uuid.uuid4().hex
        if not self.store.acquire_setup(lease):
            raise SetupError('setup_busy', 409)
        report = None
        try:
            async with asyncio.timeout(45):
                async with httpx.AsyncClient(base_url=self.base_url, timeout=8,
                        follow_redirects=False, trust_env=False, transport=self.transport,
                        headers={'Accept-Encoding': 'identity', 'Authorization':
                                 'MediaBrowser Client="NOVA Control", Device="Server", '
                                 'DeviceId="nova-setup-'+lease+'", Version="0.3.0-dev"'}) as client:
                    try:
                        report = await self._run(client, payload, configure, lease)
                    finally:
                        if ', Token=' in client.headers['Authorization']:
                            try:
                                await self._request(client, 'POST', '/Sessions/Logout')
                            except (SetupError, httpx.HTTPError):
                                pass
            return report
        except (TimeoutError, httpx.HTTPError):
            raise SetupError('jellyfin_unreachable') from None
        finally:
            self.store.finish_setup(lease, report)

    async def _request(self, client, method, path, *, allow_unauthorized=False, **kwargs):
        async with client.stream(method, path, **kwargs) as response:
            if allow_unauthorized and response.status_code == 401:
                return None
            if response.status_code in (401, 403):
                raise SetupError('jellyfin_credentials_rejected', 403)
            if response.status_code not in (200, 204):
                raise SetupError('jellyfin_request_failed')
            if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise SetupError('jellyfin_invalid_response')
            content = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=4096):
                if len(content) + len(chunk) > 262144:
                    raise SetupError('jellyfin_response_too_large')
                content.extend(chunk)
            if not content:
                return None
            try:
                return json.loads(content)
            except (ValueError, UnicodeError, RecursionError):
                raise SetupError('jellyfin_invalid_response') from None

    async def _authenticate(self, client, payload, server_id, optional=False):
        data = await self._request(client, 'POST', '/Users/AuthenticateByName',
                                  json={'Username': payload.username,
                                        'Pw': payload.password.get_secret_value()},
                                  allow_unauthorized=optional)
        if data is None and optional:
            return False
        if not isinstance(data, dict):
            raise SetupError('jellyfin_invalid_response')
        access = data.get('AccessToken')
        # Register the token for cleanup even if the returned account is not an administrator.
        if isinstance(access, str) and 1 <= len(access) <= 1024 and access.isascii() and access.isalnum():
            # Current Jellyfin disables legacy X-Emby-Token authentication.
            client.headers['Authorization'] += ', Token="'+access+'"'
        else:
            raise SetupError('jellyfin_invalid_response')
        user = data.get('User')
        if data.get('ServerId') != server_id or not isinstance(user, dict) or \
                not isinstance(user.get('Policy'), dict) or user['Policy'].get('IsAdministrator') is not True:
            raise SetupError('jellyfin_admin_required', 403)
        return True

    async def _run(self, client, payload, configure, lease):
        info = await self._request(client, 'GET', '/System/Info/Public')
        if not isinstance(info, dict) or info.get('ProductName') != 'Jellyfin Server' or \
                not isinstance(info.get('Id'), str) or not 1 <= len(info['Id']) <= 128 or \
                type(info.get('StartupWizardCompleted')) is not bool:
            raise SetupError('jellyfin_invalid_identity')
        sid = info['Id']
        if (self.expected_id and self.expected_id != sid) or not self.store.pin_setup_server(lease, sid):
            raise SetupError('jellyfin_identity_changed', 409)
        pending = not info['StartupWizardCompleted']
        if pending and not configure:
            raise SetupError('jellyfin_setup_required', 409)
        if pending:
            await self._request(client, 'GET', '/Startup/User')
        authenticated = await self._authenticate(client, payload, sid, optional=pending)
        if pending:
            if not authenticated and len(payload.password.get_secret_value()) < 14:
                raise SetupError('new_password_too_short', 422)
            if not authenticated:
                await self._request(client, 'POST', '/Startup/User',
                                    json={'Name': payload.username, 'Password': payload.password.get_secret_value()})
                await self._authenticate(client, payload, sid)
            await self._request(client, 'POST', '/Startup/Configuration', json={
                'ServerName': payload.server_name, 'UICulture': 'pt-PT',
                'MetadataCountryCode': 'PT', 'PreferredMetadataLanguage': 'pt'})
            await self._request(client, 'POST', '/Startup/RemoteAccess', json={'EnableRemoteAccess': False})
            await self._request(client, 'POST', '/Startup/Complete')
        for root in ('source-a', 'source-b'):
            path = '/media/'+root
            await self._request(client, 'POST', '/Environment/ValidatePath',
                                json={'Path': path, 'IsFile': False, 'ValidateWritable': False})
            await self._request(client, 'GET', '/Environment/DirectoryContents',
                                params={'path': path, 'includeFiles': 'false', 'includeDirectories': 'false'})
        libraries = await self._libraries(client)
        if configure:
            missing = []
            # Check ALL conflicts before adding any library.
            for desired in payload.libraries:
                paths = {'/media/'+root for root in desired.roots}
                match = None
                for existing in libraries:
                    same_name = existing['Name'].casefold() == desired.name.casefold()
                    overlap = bool(paths.intersection(existing['Locations']))
                    if same_name or overlap:
                        if not same_name or set(existing['Locations']) != paths or \
                                existing.get('CollectionType') != desired.collection_type:
                            raise SetupError('library_conflict', 409)
                        if match is not None:
                            raise SetupError('library_conflict', 409)
                        match = existing
                if match is None:
                    missing.append(desired)
            for desired in missing:
                await self._request(client, 'POST', '/Library/VirtualFolders',
                    params={'name': desired.name, 'collectionType': desired.collection_type,
                            'refreshLibrary': 'false'}, json={'LibraryOptions': {
                        'PathInfos': [{'Path': '/media/'+root} for root in desired.roots],
                        'EnableRealtimeMonitor': False, 'SaveLocalMetadata': False,
                        'TypeOptions': [{'Type': kind, 'MetadataFetchers': [], 'ImageFetchers': []}
                                        for kind in ('Movie', 'Series', 'Season', 'Episode')]}})
            libraries = await self._libraries(client)
            await self._request(client, 'POST', '/Library/Refresh')
        observed = []
        for lib in libraries:
            if not set(lib['Locations']).intersection({'/media/source-a', '/media/source-b'}):
                continue
            count = await self._request(client, 'GET', '/Items', params={
                'ParentId': lib['ItemId'], 'Recursive': 'true', 'IncludeItemTypes': 'Movie,Episode', 'Limit': 0})
            if not isinstance(count, dict) or type(count.get('TotalRecordCount')) is not int or count['TotalRecordCount'] < 0:
                raise SetupError('jellyfin_invalid_response')
            observed.append({'id': lib['ItemId'], 'name': lib['Name'], 'paths': lib['Locations'],
                             'indexed_items': count['TotalRecordCount']})
        return {'server_id': sid, 'observed_at': int(time.time()), 'wizard_completed': True,
                'directories_listable': True, 'read_only_verified': None,
                'indexing_requested': configure, 'libraries': observed}

    async def _libraries(self, client):
        data = await self._request(client, 'GET', '/Library/VirtualFolders')
        if not isinstance(data, list) or any(not isinstance(lib, dict) or
                not isinstance(lib.get('Name'), str) or not isinstance(lib.get('ItemId'), str) or
                not isinstance(lib.get('Locations'), list) or
                any(not isinstance(path, str) for path in lib['Locations']) for lib in data):
            raise SetupError('jellyfin_invalid_response')
        return data
