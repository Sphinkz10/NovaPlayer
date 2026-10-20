"""Account/library grants backed by restricted Jellyfin users; never a general proxy."""
import asyncio
import json
import re
import secrets
import time
import uuid

import httpx
from cryptography.exceptions import InvalidTag
from pydantic import Field
from .setup import Credentials,JellyfinSetup,SetupError
from .devices import Devices,DeviceError
from .secret_vault import SecretVault

UUID=r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'


def jf_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-fA-F0-9]{32}|[a-fA-F0-9-]{36}',value):
        raise SetupError('invalid_library',422)
    return uuid.UUID(value).hex


class MemberConfiguration(Credentials):
    subject: str=Field(pattern=UUID)
    libraries: list[str]=Field(min_length=1,max_length=2)


class Members:
    def __init__(self,store,base_url,transport=None):
        self.store,self.base_url,self.transport=store,base_url,transport
        self.setup=JellyfinSetup(store,base_url,transport=transport)
        self.vault=SecretVault(store)

    def list(self):
        with self.store._db() as db:
            rows={row[0]:{'subject':row[0],'username':row[1],'disabled':bool(row[2]),'revision':row[3],
                         'libraries':json.loads(row[4]) if row[4] else []}
                  for row in db.execute('SELECT subject,username,disabled,revision,policy FROM member_accounts')}
            for table in ('device_requests','devices'):
                for subject,name in db.execute('SELECT DISTINCT account_id,account_name FROM '+table+' WHERE account_id IS NOT NULL AND expires_at>?',(int(time.time()),)):
                    rows.setdefault(subject,{'subject':subject,'username':name,'disabled':True,'revision':0,'libraries':[]})
        return list(rows.values())

    def revoke(self,subject):
        with self.store._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('UPDATE member_accounts SET disabled=1,credential=NULL,revision=revision+1 WHERE subject=?',(subject,)).rowcount:
                raise DeviceError('unknown_member',404)
            for device, in db.execute('SELECT id FROM devices WHERE account_id=?',(subject,)):
                Devices._revoke(db,device,int(time.time()),'member.revoked')
        return {'revoked':True,'subject':subject}

    def _headers(self,subject):
        return {'Accept-Encoding':'identity','Authorization':'MediaBrowser Client="NOVA", Device="Server", '
                'DeviceId="nova-member-'+subject+'", Version="0.3.0"'}

    def _client(self,headers):
        return httpx.AsyncClient(base_url=self.base_url,headers=headers,transport=self.transport,
                                 trust_env=False,follow_redirects=False,timeout=8)

    async def configure(self,payload):
        observed=self.store.setup_state()['last_observation']
        if not observed:raise SetupError('jellyfin_setup_required',409)
        wanted={jf_id(value) for value in payload.libraries}
        available={jf_id(lib['id']):{'id':jf_id(lib['id']),'name':lib['name']} for lib in observed['libraries']}
        if not wanted.issubset(available):raise SetupError('invalid_library',422)
        choices={member['subject']:member for member in self.list()}
        if payload.subject not in choices:raise SetupError('unverified_directory_account',409)
        lease=uuid.uuid4().hex
        if not self.store.acquire_setup(lease):raise SetupError('setup_busy',409)
        subject=payload.subject; username='nova-'+subject.replace('-','')
        try:
            with self.store._db() as db:
                db.execute('BEGIN IMMEDIATE')
                previous=db.execute('SELECT jellyfin_user,server_id FROM member_accounts WHERE subject=?',(subject,)).fetchone()
                if not previous and db.execute('SELECT COUNT(*) FROM member_accounts').fetchone()[0]>=50:
                    raise SetupError('member_limit',409)
                db.execute('INSERT INTO member_accounts(subject,username) VALUES(?,?) '
                           'ON CONFLICT(subject) DO UPDATE SET disabled=1', (subject,choices[subject]['username']))
                revision=db.execute('SELECT revision FROM member_accounts WHERE subject=?',(subject,)).fetchone()[0]
            async with asyncio.timeout(50):
                async with self._client(self._headers(subject)) as admin:
                    try:
                        info=await self.setup._request(admin,'GET','/System/Info/Public')
                        if info.get('Id')!=observed['server_id']:raise SetupError('jellyfin_identity_changed',409)
                        await self.setup._authenticate(admin,payload,observed['server_id'])
                        password=secrets.token_urlsafe(48)
                        if previous and previous[0]:
                            if previous[1]!=observed['server_id']:raise SetupError('jellyfin_identity_changed',409)
                            user=await self.setup._request(admin,'GET','/Users/'+jf_id(previous[0]))
                            if user.get('Name')!=username or user.get('Policy',{}).get('IsAdministrator') is not False:
                                raise SetupError('member_identity_changed',409)
                            await self.setup._request(admin,'POST','/Users/Password',params={'userId':previous[0]},
                                                      json={'NewPw':password,'ResetPassword':False})
                        else:
                            user=await self.setup._request(admin,'POST','/Users/New',json={'Name':username,'Password':password})
                        uid=jf_id(user['Id'])
                        if user.get('Name')!=username or user.get('Policy',{}).get('IsAdministrator') is True:
                            raise SetupError('member_identity_changed',409)
                        with self.store._db() as db:
                            db.execute('UPDATE member_accounts SET jellyfin_user=?,server_id=? WHERE subject=?',
                                       (uid,observed['server_id'],subject))
                        policy=dict(user['Policy']);policy.update(IsAdministrator=False,IsHidden=True,IsDisabled=False,
                            EnableAllFolders=False,EnabledFolders=sorted(wanted),EnableContentDownloading=False,
                            EnableMediaDeletion=False,EnableMediaDeletionFromFolders=[],EnablePublicSharing=False,
                            EnableLiveTvManagement=False,EnableLiveTvAccess=False,EnableRemoteControlOfOtherUsers=False,
                            EnableSharedDeviceControl=False,EnableSyncTranscoding=False)
                        await self.setup._request(admin,'POST','/Users/'+uid+'/Policy',json=policy)
                        checked=await self.setup._request(admin,'GET','/Users/'+uid)
                        self._policy(checked,uid,wanted)
                        async with self._client(self._headers(subject)) as restricted:
                            auth=await self.setup._request(restricted,'POST','/Users/AuthenticateByName',
                                                         json={'Username':username,'Pw':password})
                            access=auth.get('AccessToken')
                            if (not isinstance(access,str) or not re.fullmatch(r'[A-Za-z0-9]{1,1024}',access) or
                                    auth.get('ServerId')!=observed['server_id']):raise SetupError('jellyfin_invalid_response')
                            self._policy(auth['User'],uid,wanted)
                            sealed=self.vault.seal(access,'member:'+subject+':'+observed['server_id'])
                        selected=[available[identity] for identity in sorted(wanted)]
                        with self.store._db() as db:
                            if not db.execute('UPDATE member_accounts SET policy=?,credential=?,disabled=0,revision=revision+1 WHERE subject=? AND revision=?',
                                              (json.dumps(selected),sealed,subject,revision)).rowcount:
                                raise SetupError('member_permissions_changed',409)
                        return {'subject':subject,'username':choices[subject]['username'],'libraries':selected,
                                'jellyfin_policy_verified':True,'administrator':False}
                    finally:
                        if ', Token=' in admin.headers['Authorization']:
                            try:await self.setup._request(admin,'POST','/Sessions/Logout')
                            except (SetupError,httpx.HTTPError):pass
        except (TimeoutError,httpx.HTTPError):
            raise SetupError('jellyfin_unreachable') from None
        except (ValueError,KeyError,TypeError,OSError,InvalidTag):
            raise SetupError('jellyfin_member_configuration_failed') from None
        finally:
            self.store.finish_setup(lease)

    @staticmethod
    def _policy(user,uid,wanted):
        policy=user.get('Policy',{})
        if (jf_id(user.get('Id'))!=uid or policy.get('IsAdministrator') is not False or
                policy.get('IsDisabled') is not False or policy.get('EnableAllFolders') is not False or
                {jf_id(value) for value in policy.get('EnabledFolders',[])}!=wanted):
            raise SetupError('jellyfin_member_policy_changed',409)

    async def authorization(self,access):
        devices=Devices(self.store);identity=devices.authenticate(access);subject=identity['account_id']
        if not subject:raise DeviceError('member_permissions_required',403)
        with self.store._db() as db:
            row=db.execute('SELECT jellyfin_user,server_id,policy,credential,revision FROM member_accounts WHERE subject=? AND disabled=0',(subject,)).fetchone()
        if not row or not row[3]:raise DeviceError('member_permissions_required',403)
        uid,sid,raw,sealed,revision=row;libraries=json.loads(raw)
        try:
            credential=self.vault.open(sealed,'member:'+subject+':'+sid)
            headers=self._headers(subject);headers['Authorization']+=', Token="'+credential+'"'
            async with asyncio.timeout(15):
                async with self._client(headers) as client:
                    info=await self.setup._request(client,'GET','/System/Info/Public')
                    if info.get('Id')!=sid:raise SetupError('jellyfin_identity_changed',409)
                    user=await self.setup._request(client,'GET','/Users/'+uid)
                    self._policy(user,uid,{lib['id'] for lib in libraries})
            devices.authenticate(access)  # Re-check revocation after network I/O.
            with self.store._db() as db:
                if not db.execute('SELECT 1 FROM member_accounts WHERE subject=? AND disabled=0 AND revision=?',(subject,revision)).fetchone():
                    raise DeviceError('member_permissions_changed',403)
            return {'server_id':identity['server_id'],'device_id':identity['device_id'],'account_id':subject,
                    'revision':revision,'libraries':libraries,'catalog_enabled':True,'media_enabled':True}
        except (ValueError,KeyError,TypeError,OSError,InvalidTag,TimeoutError,httpx.HTTPError):
            raise DeviceError('member_authorization_unavailable',503) from None
