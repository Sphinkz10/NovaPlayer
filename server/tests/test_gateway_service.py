import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from nova_server.app import make_app
from nova_server.gateway_channel import GatewayChannel, GatewayPublisher, atomic_private
from nova_server.gateway_service import DurableLeases, GatewayWorker, exclusive, load_config
from nova_server.wireguard_gateway import GatewayError, reconcile
from nova_server.wireguard import WireGuardEnrollments
from test_wireguard_gateway import Backend, policy, snapshot
from test_wireguard_enrollment import lab, key, request, approve


class Clock:
    wall = 1000
    mono = 10
    def time(self): return self.wall
    def monotonic(self): return self.mono


@pytest.fixture
def service(tmp_path):
    config = policy(); clock = Clock()
    channel_dir = tmp_path/'channel'; channel_dir.mkdir(mode=0o700)
    lease_dir = tmp_path/'leases'; lease_dir.mkdir(mode=0o700)
    secret = tmp_path/'channel.key'; atomic_private(secret, os.urandom(32))
    channel = GatewayChannel(channel_dir, secret)
    data = snapshot(config, [key(), key()])
    class Enrollments:
        def gateway_plan(self):
            return {**data, 'issued_at': clock.wall, 'expires_at': clock.wall+15}
    publisher = GatewayPublisher(Enrollments(), channel, clock=clock.time, monotonic=clock.monotonic)
    publisher.active = True
    backend = Backend()
    leases = DurableLeases(lease_dir, config)
    worker = GatewayWorker(config, backend, channel, leases, clock=clock.time, monotonic=clock.monotonic)
    return config, clock, channel, data, publisher, backend, leases, worker


def test_worker_durable_ips_survive_interface_and_process_rebuild(service):
    config, clock, channel, data, publisher, backend, leases, worker = service
    assert publisher.status()['state'] == 'not_verified'
    publisher.publish(); assert worker.tick()
    before = dict(backend.state)
    assert publisher.status()['configuration_observed']
    assert not publisher.status()['remote_access_enabled']
    assert not publisher.status()['handshake_verified']
    # Add a lower-sorting device, rebuild both interface and service, and ensure
    # previous devices do not move to different /32s.
    data['peers'].append({'device_id':str(uuid.UUID(int=1)), 'public_key':key()})
    backend.state.clear()
    restarted = GatewayWorker(config, backend, channel, DurableLeases(leases.path.parent, config),
                              clock=clock.time, monotonic=clock.monotonic)
    publisher.publish(); assert restarted.tick()
    assert all(backend.state[public] == routes for public, routes in before.items())
    operations = len(backend.commands)
    assert restarted.tick() and len(backend.commands) == operations
    data['peers'].clear(); publisher.publish(); assert restarted.tick()
    assert backend.state == {} and publisher.status()['peers'] == []


@pytest.mark.parametrize('failure', ['missing', 'signature', 'expired', 'future', 'replaced_identity', 'unknown_field', 'oversized'])
def test_transport_failure_clears_owned_peers_and_invalidates_previous_report(service, failure):
    config, clock, channel, data, publisher, backend, leases, worker = service
    publisher.publish(); assert worker.tick() and backend.state
    if failure == 'missing': (channel.directory/'plan.json').unlink()
    elif failure == 'signature':
        envelope = json.loads((channel.directory/'plan.json').read_text())
        envelope['signature'] = '0'*64
        atomic_private(channel.directory/'plan.json', json.dumps(envelope).encode())
    elif failure == 'oversized': atomic_private(channel.directory/'plan.json', b'x'*32769)
    else:
        plan = channel.read('plan')
        if failure == 'expired': clock.wall += 15
        elif failure == 'future': plan['snapshot']['issued_at'] += 1
        elif failure == 'replaced_identity': plan['snapshot']['server_id'] = str(uuid.uuid4())
        elif failure == 'unknown_field': plan['shell'] = 'untrusted-sentinel'
        channel.write('plan', plan)
    assert not worker.tick() and not backend.state
    assert publisher.status()['state'] == 'not_verified'
    assert 'untrusted-sentinel' not in json.dumps(channel.read('observation'))


def test_expiry_uses_monotonic_clock_and_changed_plan_id_cannot_extend_existing_plan(service):
    _, clock, channel, _, publisher, backend, _, worker = service
    publisher.publish(); assert worker.tick()
    original = channel.read('plan')
    clock.mono += 16  # simulate wall-clock rollback/paused clock
    assert not worker.tick() and not backend.state
    assert publisher.status()['state'] == 'not_verified'
    channel.write('plan', original)
    assert not worker.tick()
    publisher.publish(); assert worker.tick()  # only a fresh, authenticated plan may apply


def test_control_countdown_uses_remaining_server_monotonic_validity(service):
    _, clock, _, _, publisher, _, _, worker = service
    publisher.publish(); assert worker.tick()
    assert publisher.status()['valid_for_seconds'] == 15
    clock.mono += 7
    assert publisher.status()['valid_for_seconds'] == 8
    clock.wall += 14
    assert publisher.status()['valid_for_seconds'] == 1


def test_readback_failure_or_unreachable_gateway_never_reports_removal_success(service):
    _, _, channel, _, publisher, backend, _, worker = service
    publisher.publish(); backend.lie = True
    assert not worker.tick() and channel.read('observation')['configuration_observed'] is False
    backend.lie = False; assert worker.tick()
    def unreachable(_): raise RuntimeError('private-error-sentinel')
    backend.verify_scope = unreachable
    assert not worker.tick()
    report = channel.read('observation')
    assert report['cleanup_confirmed'] is False and 'private-error-sentinel' not in json.dumps(report)


def test_report_not_trusted_after_core_restart_revocation_or_expiry(service):
    _, clock, channel, data, publisher, _, _, worker = service
    publisher.publish(); assert worker.tick()
    assert publisher.status()['configuration_observed']
    restarted = GatewayPublisher(publisher.enrollments, channel, clock=clock.time, monotonic=clock.monotonic)
    restarted.active = True
    assert restarted.status()['state'] == 'not_verified'
    approved = data['peers'].pop()
    assert publisher.status()['state'] == 'not_verified'
    data['peers'].append(approved)
    clock.wall += 15
    assert publisher.status()['state'] == 'not_verified'


@pytest.mark.parametrize('field,value', [('handshake_verified', True), ('server_id', str(uuid.uuid4())),
    ('configuration_observed', False), ('peers', []), ('peers', [{'device_id':'x'}])])
def test_malformed_or_overclaiming_observation_is_not_an_applied_claim(service, field, value):
    _, _, channel, _, publisher, _, _, worker = service
    publisher.publish(); assert worker.tick()
    report = channel.read('observation'); report['result'][field] = value
    channel.write('observation', report)
    assert publisher.status()['state'] == 'not_verified'


def test_report_role_substitution_or_unsigned_status_is_rejected(service):
    _, _, channel, _, publisher, _, _, worker = service
    publisher.publish(); assert worker.tick()
    atomic_private(channel.directory/'observation.json', (channel.directory/'plan.json').read_bytes())
    assert publisher.status()['state'] == 'not_verified'
    atomic_private(channel.directory/'observation.json', b'{"configuration_observed":true}')
    assert publisher.status()['state'] == 'not_verified'


def test_policy_identity_change_and_corrupted_saved_address_are_refused(service):
    config, _, _, _, publisher, _, leases, worker = service
    publisher.publish(); assert worker.tick()
    other = policy()
    with pytest.raises(GatewayError, match='identity_changed'):
        DurableLeases(leases.path.parent, other)
    with leases._db() as db: db.execute("UPDATE leases SET address='0.0.0.0/0' WHERE rowid=1")
    assert not worker.tick()


def test_persistent_assignments_are_validated_before_kernel_mutation(service):
    config, clock, _, data, _, backend, _, _ = service
    for assignments in ({}, {peer['public_key']:'0.0.0.0/0' for peer in data['peers']},
                        {peer['public_key']:'10.222.0.2/32' for peer in data['peers']}):
        with pytest.raises(GatewayError):
            reconcile(data, config, backend, assignments=assignments, clock=clock.time)
    assert not backend.commands


def test_gateway_status_is_owner_only_and_does_not_enable_remote_access(lab):
    admin, client, _, _ = lab
    path = '/api/v1/admin/connect/wireguard/gateway'
    assert admin.get(path).json()['state'] == 'disabled'
    assert admin.get(path, headers=dict(client.headers)).status_code == 401
    assert client.get(path).status_code == 404


@pytest.mark.skipif(sys.platform != 'linux', reason='POSIX private files and process locks')
def test_private_files_symlinks_and_single_process_locks(service, tmp_path):
    _, _, channel, _, _, _, _, _ = service
    with exclusive(channel.directory, 'worker'):
        with pytest.raises(GatewayError, match='already_running'):
            with exclusive(channel.directory, 'worker'): pass
    channel.write('plan', {})
    (channel.directory/'plan.json').chmod(0o644)
    with pytest.raises(GatewayError): channel.read('plan')
    (channel.directory/'plan.json').unlink()
    (channel.directory/'plan.json').symlink_to(tmp_path/'channel.key')
    with pytest.raises(GatewayError): channel.read('plan')
    with exclusive(channel.directory, 'worker'): pass  # released lock is reusable


@pytest.mark.skipif(sys.platform != 'linux', reason='Opt-in Linux publisher lifecycle')
def test_core_lifecycle_publishes_approvals_confirms_then_withdraws_on_shutdown(tmp_path):
    from nova_server.storage import Store
    from nova_server.devices import Devices
    from test_wireguard_enrollment import associate
    channel_dir = tmp_path/'channel'; channel_dir.mkdir(mode=0o700)
    lease_dir = tmp_path/'leases'; lease_dir.mkdir(mode=0o700)
    secret = tmp_path/'key'; atomic_private(secret, os.urandom(32))
    store = Store(tmp_path/'core'); store.bootstrap('owner', 'unused')
    owner = 'a'*48; store.save_session(owner)
    tokens = associate(Devices(store)); enrollments = WireGuardEnrollments(store)
    item = enrollments.request(tokens['access_token'], key())
    enrollments.decide(item['device_id'], item['revision'], True)
    config = policy()
    config = type(config)(Devices(store).identity(), config.public_key, config.pool, config.gateway)
    channel = GatewayChannel(channel_dir, secret); backend = Backend()
    worker = GatewayWorker(config, backend, channel, DurableLeases(lease_dir, config))
    app = make_app(store.dir, allowed_hosts=['testserver'],
                   gateway_options={'directory':channel_dir, 'secret_file':secret})
    path = '/api/v1/admin/connect/wireguard/gateway'
    with TestClient(app) as admin:
        admin.headers['Authorization'] = 'Bearer '+owner
        assert worker.tick()
        assert admin.get(path).json()['state'] == 'configuration_observed'
        Devices(store).revoke(tokens['device_id'])
        assert admin.get(path).json()['state'] == 'not_verified'  # before next publication
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            worker.tick()
            if not backend.state: break
            time.sleep(.1)
        assert not backend.state
        assert admin.get(path).json()['state'] == 'configuration_observed'
    assert not (channel_dir/'plan.json').exists()
    assert not worker.tick() and channel.read('observation')['cleanup_confirmed']


def test_run_cleans_peers_on_ordinary_process_shutdown(service):
    _, _, _, _, publisher, backend, _, worker = service
    publisher.publish()
    stopping = threading.Event()
    def after_tick():
        result = original_tick(); stopping.set(); return result
    original_tick = worker.tick; worker.tick = after_tick
    worker.run(stopping, interval=.001)
    assert not backend.state


def test_local_config_cannot_inject_namespace_commands_or_use_relative_paths(service, tmp_path):
    from dataclasses import asdict
    config, _, channel, _, _, _, leases, _ = service
    raw = {'schema_version':1, 'policy':asdict(config), 'namespace':'nova-wg-test', 'interface':'wg0',
           'channel_directory':str(channel.directory.resolve()), 'secret_file':str(tmp_path/'channel.key'),
           'lease_directory':str(leases.path.parent.resolve())}
    path = tmp_path/'gateway.json'; atomic_private(path, json.dumps(raw).encode())
    assert load_config(path)[1] == config
    for changes in ({'namespace':'nova-wg-a; touch bad'}, {'namespace':'../shared'},
                    {'channel_directory':'relative'}, {'shell':'arbitrary command'}, {'schema_version':True}):
        atomic_private(path, json.dumps({**raw, **changes}).encode())
        with pytest.raises((GatewayError, ValueError)): load_config(path)
