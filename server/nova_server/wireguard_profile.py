"""Authenticated device provisioning of public WireGuard parameters only."""
import ipaddress
import json
import time
from urllib.parse import urlsplit

from .devices import DeviceError
from .gateway_channel import GatewayChannel, GatewayPublisher, read_private
from .wireguard import WireGuardEnrollments
from .wireguard_gateway import GatewayPolicy, GatewaySnapshot, GatewayError


class WireGuardProfiles:
    def __init__(self, store, config, channel, *, clock=time.time, monotonic=time.monotonic):
        from scripts.wireguard_install import endpoint
        if set(config) != {'schema_version','policy','endpoint','client_origin'} or type(config['schema_version']) is not int or config['schema_version'] != 1:
            raise ValueError('Invalid remote public configuration')
        self.policy = GatewayPolicy(**config['policy'])
        self.endpoint = endpoint(config['endpoint'])
        self.origin = config['client_origin']
        parsed = urlsplit(self.origin)
        if (parsed.scheme != 'https' or parsed.hostname != self.policy.gateway or parsed.port is None
                or not 1024 <= parsed.port <= 65535 or self.origin != f'https://{self.policy.gateway}:{parsed.port}'):
            raise ValueError('Private exact gateway HTTPS origin required')
        self.enrollments = WireGuardEnrollments(store, clock=clock)
        self.channel, self.clock, self.monotonic = channel, clock, monotonic
        self.reader = GatewayPublisher(self.enrollments, channel, clock=clock, monotonic=monotonic)
        self.last_wall = 0

    @classmethod
    def local(cls, store, path):
        return cls(store,json.loads(read_private(path,8192)),GatewayChannel('/channel','/identity/channel.key'))

    def issue(self, access):
        current = self.enrollments.status(access)
        if current['state'] != 'approved':
            raise DeviceError('wireguard_approval_required',403)
        try:
            # Read-only consumer in the isolated client process: authenticate both
            # files, bind report to the currently published plan and live DB set.
            # Cache monotonic deadlines so repeated requests cannot extend them.
            with self.reader.lock:
                now = int(self.clock())
                if now < self.last_wall:raise GatewayError('gateway_clock_rollback')
                self.last_wall = now
                plan = self.channel.read('plan')
                if set(plan) != {'schema_version','publisher_id','plan_id','snapshot'} or plan['schema_version'] != 1:
                    raise GatewayError('gateway_plan_invalid')
                snapshot = GatewaySnapshot.model_validate(plan['snapshot'])
                if (snapshot.server_id != self.policy.server_id or not snapshot.issued_at <= now < snapshot.expires_at
                        or not 0 < snapshot.expires_at-snapshot.issued_at <= 15):
                    raise GatewayError('gateway_plan_invalid')
                mono = self.monotonic()
                if self.reader.identity != plan['publisher_id']:
                    self.reader.pending.clear();self.reader.identity = plan['publisher_id']
                # Retain expired entries until WALL expiry to reject clock stalls.
                self.reader.pending = {key:value for key,value in self.reader.pending.items()
                    if value[0]['snapshot']['expires_at'] > now}
                if len(self.reader.pending) >= 64:raise GatewayError('gateway_plan_window_full')
                self.reader.pending.setdefault(plan['plan_id'],(plan,mono+snapshot.expires_at-now))
                if self.reader.pending[plan['plan_id']][0] != plan:raise GatewayError('gateway_plan_changed')
                self.reader.active = True
                observed = self.reader.status()
            if not observed['configuration_observed']:raise GatewayError('gateway_not_observed')
            peer = next(p for p in observed['peers'] if p['device_id'] == current['device_id'] and p['public_key'] == current['public_key'])
            address = ipaddress.IPv4Network(peer['address'])
            pool = ipaddress.IPv4Network(self.policy.pool)
            if (address.prefixlen != 32 or address.network_address not in pool or str(address.network_address) == self.policy.gateway
                    or address.network_address in (pool.network_address,pool.broadcast_address)):
                raise GatewayError('gateway_address_invalid')
        except (OSError,ValueError,KeyError,TypeError,StopIteration,GatewayError):
            raise DeviceError('wireguard_gateway_unavailable',503) from None
        # Revocation/disable during the channel read must prevent issuance.
        if self.enrollments.status(access) != current:
            raise DeviceError('wireguard_enrollment_changed',409)
        return {'schema_version':1,'server_id':current['server_id'],'device_id':current['device_id'],
            'public_key':current['public_key'],'revision':current['revision'],'address':peer['address'],
            'gateway_public_key':self.policy.public_key,'endpoint':self.endpoint,'client_origin':self.origin,
            'allowed_ip':self.policy.gateway+'/32','issued_at':now,'expires_at':now+86400,
            'handshake_verified':False}
