"""Real WireGuard Android -> isolated Linux namespace -> NOVA TLS 1.3.

Disposable GitHub emulator only. Never run against a NAS or configure host routes
to the private HTTPS address. The host proxy transports encrypted UDP only.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import select
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'connect/test-results/wireguard'
PACKAGE = 'com.novacinema.connect.poc'
GW, CLIENT, UNDERLAY = '10.222.0.1', '10.222.0.2', '10.203.0.2'
ORIGIN = 'https://'+GW+':9444'
sys.path.insert(0, str(ROOT/'server'))


def command(*args, check=True, data=None):
    result = subprocess.run(list(map(str, args)), input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=30)
    if check and result.returncode:
        raise RuntimeError('Proof command failed: '+str(args[0]))
    return result


def adb(*args, check=True):
    return command('adb', *args, check=check).stdout.decode(errors='replace')


def push_private(name, data):
    assert name in ('wireguard-fixture.json', 'wireguard-gate.txt')
    command('adb', 'shell', '-T', 'run-as', PACKAGE, 'tee', 'files/'+name, data=data)


def certificate(root, name):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'NOVA disposable WireGuard proof')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=2))
            .not_valid_after(now+timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host))
                            for host in (GW, '10.0.2.2', '127.0.0.1')]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
            .sign(key, hashes.SHA256()))
    pem = cert.public_bytes(serialization.Encoding.PEM)
    (root/(name+'.crt')).write_bytes(pem)
    private = root/(name+'.key')
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    private.chmod(0o600)
    return pem.decode('ascii')


class UdpRelay:
    """One-emulator UDP transport; cannot decrypt WireGuard or forward TCP."""
    def __init__(self):
        self.front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.front.bind(('127.0.0.1', 0)); self.port = self.front.getsockname()[1]
        self.back = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.back.connect((UNDERLAY, 51820))
        self.done = threading.Event(); self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        peer = None
        while not self.done.is_set():
            try:
                readable, _, _ = select.select([self.front, self.back], [], [], .2)
                for source in readable:
                    if source is self.front:
                        data, peer = self.front.recvfrom(65535); self.back.send(data)
                    else:
                        data = self.back.recv(65535)
                        if peer is not None: self.front.sendto(data, peer)
            except OSError:
                if not self.done.is_set(): raise

    def close(self):
        self.done.set(); self.thread.join(2); self.front.close(); self.back.close()


def serve(root, bootstrap_port=None):
    import uvicorn
    from nova_server.client_api import make_client_app
    os.environ['NOVA_STATE_DIR'] = str(root/'state')
    # Live canaries prove the denied ports are not simply absent services.
    def canary(port):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('0.0.0.0', port)); listener.listen()
            while True:
                connection, _ = listener.accept(); connection.close()
    if bootstrap_port is None:
        for port in (22, 9443): threading.Thread(target=canary, args=(port,), daemon=True).start()
    origin = ORIGIN if bootstrap_port is None else 'https://10.0.2.2:'+str(bootstrap_port)
    runtime = uvicorn.Config(make_client_app(origin=origin), host=GW if bootstrap_port is None else '127.0.0.1',
                             port=bootstrap_port or 9444,
                             ssl_certfile=str(root/'client.crt'), ssl_keyfile=str(root/'client.key'),
                             access_log=False, proxy_headers=False, log_level='error')
    runtime.load(); runtime.ssl.minimum_version = ssl.TLSVersion.TLSv1_3
    uvicorn.Server(runtime).run()


def check_services(root):
    import httpx
    with httpx.Client(verify=ssl.create_default_context(cafile=str(root/'client.crt')),
                      trust_env=False, timeout=1) as client:
        assert client.get(ORIGIN+'/api/v1/device/me').status_code == 401
    for port in (22, 9443):
        with socket.create_connection(('127.0.0.1', port), timeout=1): pass


def consent():
    deadline = time.monotonic()+25
    while time.monotonic() < deadline:
        adb('shell', 'uiautomator', 'dump', '/sdcard/nova-wg-consent.xml')
        xml = adb('shell', 'cat', '/sdcard/nova-wg-consent.xml')
        nodes = list(ET.fromstring(xml).iter('node'))
        positive = [n for n in nodes if n.get('package') == 'com.android.vpndialogs'
                    and n.get('resource-id') == 'android:id/button1' and n.get('enabled') == 'true']
        if positive:
            (OUT/'android-vpn-consent.xml').write_text(xml)
            bounds = list(map(int, re.findall(r'\d+', positive[0].get('bounds', ''))))
            assert len(bounds) == 4
            adb('shell', 'input', 'tap', str((bounds[0]+bounds[2])//2), str((bounds[1]+bounds[3])//2))
            return
        time.sleep(.25)
    raise RuntimeError('Android VPN consent dialog not observed')


def instrument(mode, callback=lambda stage: None):
    process = subprocess.Popen(['adb', 'shell', 'am', 'instrument', '-w', '-r', '-e', 'mode', mode,
                                PACKAGE+'.test/com.novacinema.connect.WireGuardNetworkInstrumentation'],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    timer = threading.Timer(240, process.kill); timer.start()
    lines = []
    try:
        for line in process.stdout:
            lines.append(line)
            match = re.search(r'INSTRUMENTATION_STATUS: wireguard_stage=([a-z-]+)', line)
            if match: callback(match[1])
        process.wait(timeout=10)
    finally:
        timer.cancel()
        if process.poll() is None: process.kill(); process.wait(timeout=5)
    output = ''.join(lines)
    (OUT/(mode+'.txt')).write_text(output)
    if 'INSTRUMENTATION_RESULT: nova_wireguard=passed' not in output:
        # Instrumentation reports only class/line, never exception messages or secrets.
        safe = '\n'.join(line for line in lines if 'INSTRUMENTATION_RESULT:' in line)
        raise AssertionError(safe)
    assert 'INSTRUMENTATION_CODE: -1' in output
    checks = re.search(r'INSTRUMENTATION_RESULT: checks=(.+)', output).group(1).strip().split('|')
    return checks


def run():
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true'
            or adb('shell', 'getprop', 'ro.kernel.qemu').strip() != '1'):
        raise SystemExit('Only a disposable Linux GitHub Actions emulator is permitted')
    OUT.mkdir(parents=True, exist_ok=True)
    # Synchronise only the isolated emulator RTC; retain real certificate validation.
    command('adb', 'root', check=False); adb('wait-for-device')
    assert adb('shell', 'id', '-u').strip() == '0'
    adb('shell', 'date', '-u', datetime.now(timezone.utc).strftime('%m%d%H%M%Y.%S'))
    assert abs(int(adb('shell', 'date', '+%s').strip())-time.time()) < 5
    for path in ('app/build/outputs/apk/debug/app-debug.apk',
                 'app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk'):
        adb('install', '-r', '-t', str(ROOT/'connect'/path))
    adb('shell', 'run-as', PACKAGE, 'mkdir', '-p', 'files')
    suffix = secrets.token_hex(3)
    namespace, host_link, ns_link = 'nova-wg-'+suffix, 'nwh'+suffix, 'nwn'+suffix
    def ip(*args, check=True): return command('sudo', 'ip', *args, check=check)
    def ns(*args, check=True): return command('sudo', 'ip', 'netns', 'exec', namespace, *args, check=check)
    created = False; link_created = False; server = None; relay = None; bootstrap = None
    handshake = {}; checks = []
    with tempfile.TemporaryDirectory(prefix='nova-wireguard-network-') as folder:
        root = Path(folder)
        from nova_server.storage import Store
        from nova_server.devices import Devices
        from nova_server.security import hash_password
        from nova_server.wireguard import WireGuardEnrollments
        store = Store(root/'state'); assert store.bootstrap('owner', hash_password(secrets.token_urlsafe(32)))
        devices = Devices(store); request = devices.start('Disposable WireGuard TV')
        review = devices.inspect(request['user_code']); devices.decide(request['user_code'], review['request_id'], True)
        tokens = devices.poll(request['device_code'])
        pem, wrong = certificate(root, 'client'), certificate(root, 'wrong')
        private = command('wg', 'genkey').stdout.strip()
        public = command('wg', 'pubkey', data=private+b'\n').stdout.decode().strip()
        client_public = None
        key_file = root/'gateway.key'; key_file.write_bytes(private+b'\n'); key_file.chmod(0o600)
        try:
            ip('netns', 'add', namespace); created = True
            ip('link', 'add', host_link, 'type', 'veth', 'peer', 'name', ns_link); link_created = True
            ip('link', 'set', ns_link, 'netns', namespace)
            ip('addr', 'add', '10.203.0.1/30', 'dev', host_link); ip('link', 'set', host_link, 'up')
            ns('ip', 'addr', 'add', UNDERLAY+'/30', 'dev', ns_link)
            ns('ip', 'link', 'set', ns_link, 'up'); ns('ip', 'link', 'set', 'lo', 'up')
            ns('ip', 'link', 'add', 'wg0', 'type', 'wireguard')
            ns('ip', 'addr', 'add', GW+'/32', 'dev', 'wg0')
            ns('wg', 'set', 'wg0', 'listen-port', '51820', 'private-key', key_file)
            ns('ip', 'link', 'set', 'wg0', 'up'); ns('ip', 'route', 'add', CLIENT+'/32', 'dev', 'wg0')
            ns('sysctl', '-q', '-w', 'net.ipv4.ip_forward=0')
            for chain in ('INPUT', 'OUTPUT', 'FORWARD'): ns('iptables', '-P', chain, 'DROP')
            ns('iptables', '-A', 'INPUT', '-i', 'lo', '-j', 'ACCEPT')
            ns('iptables', '-A', 'OUTPUT', '-o', 'lo', '-j', 'ACCEPT')
            ns('iptables', '-A', 'INPUT', '-i', ns_link, '-s', '10.203.0.1', '-p', 'udp', '--dport', '51820', '-j', 'ACCEPT')
            ns('iptables', '-A', 'OUTPUT', '-o', ns_link, '-d', '10.203.0.1', '-p', 'udp', '--sport', '51820', '-j', 'ACCEPT')
            ns('iptables', '-A', 'INPUT', '-i', 'wg0', '-s', CLIENT, '-d', GW, '-p', 'tcp', '--dport', '9444', '-j', 'ACCEPT')
            ns('iptables', '-A', 'OUTPUT', '-o', 'wg0', '-s', GW, '-d', CLIENT, '-p', 'tcp', '--sport', '9444',
               '-m', 'conntrack', '--ctstate', 'ESTABLISHED', '-j', 'ACCEPT')
            server = subprocess.Popen(['sudo', 'ip', 'netns', 'exec', namespace, sys.executable,
                                       str(Path(__file__).resolve()), '--serve', str(root)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(50):
                if server.poll() is not None: raise RuntimeError('Private namespace service exited')
                if ns(sys.executable, Path(__file__).resolve(), '--check-services', root, check=False).returncode == 0: break
                time.sleep(.2)
            else: raise RuntimeError('Private namespace services not ready')
            checks.append('real NOVA HTTPS and live denied-port canaries in isolated namespace')
            assert not command('ip', 'route', 'show', GW+'/32').stdout.strip()
            checks.append('host has no route or TCP forwarder to the service overlay address')
            relay = UdpRelay()
            # Separate LAN enrollment endpoint, sharing Core state but never forwarding
            # TCP to the overlay. Only the encrypted UDP relay reaches that network.
            with socket.socket() as allocation:
                allocation.bind(('127.0.0.1', 0)); bootstrap_port = allocation.getsockname()[1]
            bootstrap = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--bootstrap', str(root),
                                          '--port', str(bootstrap_port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import httpx
            with httpx.Client(verify=ssl.create_default_context(cafile=str(root/'client.crt')), trust_env=False, timeout=1) as probe:
                for _ in range(50):
                    if bootstrap.poll() is not None: raise RuntimeError('LAN enrollment service exited')
                    try:
                        assert probe.get(f'https://127.0.0.1:{bootstrap_port}/api/v1/device/me').status_code == 401
                        break
                    except httpx.ConnectError: time.sleep(.2)
                else: raise RuntimeError('LAN enrollment service not ready')
            fixture = {'origin': ORIGIN, 'server_id': devices.identity(), 'device_id': tokens['device_id'],
                       'access_token': tokens['access_token'], 'refresh_token': tokens['refresh_token'],
                       'enrollment_origin': f'https://10.0.2.2:{bootstrap_port}',
                       'gateway_public_key': public, 'endpoint_port': relay.port,
                       'certificate_pem': pem, 'wrong_certificate_pem': wrong}
            push_private('wireguard-fixture.json', json.dumps(fixture).encode())
            def callback(stage):
                nonlocal client_public
                if stage == 'consent': consent()
                elif stage == 'enrolled':
                    pending = WireGuardEnrollments(store).list()
                    assert len(pending) == 1 and pending[0]['device_id'] == tokens['device_id'] and pending[0]['state'] == 'pending'
                    client_public = pending[0]['public_key']
                    # Exercise the actual owner API; it records approval, never an
                    # installed claim. The disposable lab installs/readbacks separately.
                    from fastapi.testclient import TestClient
                    from nova_server.app import make_app
                    owner_access = secrets.token_urlsafe(48); store.save_session(owner_access)
                    with TestClient(make_app(store.dir, allowed_hosts=['testserver'])) as owner:
                        decision = owner.post('/api/v1/admin/connect/wireguard/enrollments/'+tokens['device_id'],
                            headers={'Authorization':'Bearer '+owner_access}, json={'revision':1,'approve':True})
                        assert decision.status_code == 200 and decision.json()['gateway_state'] == 'not_verified'
                    ns('wg', 'set', 'wg0', 'peer', client_public, 'allowed-ips', CLIENT+'/32')
                    assert ns('wg', 'show', 'wg0', 'allowed-ips').stdout.decode().split() == [client_public, CLIENT+'/32']
                    checks.append('owner-approved Android-generated public key installed and read back only by disposable lab')
                    push_private('wireguard-gate.txt', b'approved')
                elif stage == 'connected':
                    values = ns('wg', 'show', 'wg0', 'latest-handshakes').stdout.decode().split()
                    assert len(values) == 2 and values[0] == client_public and int(values[1]) > 0
                    transfer = ns('wg', 'show', 'wg0', 'transfer').stdout.decode().split()
                    assert len(transfer) == 3 and int(transfer[1]) > 0 and int(transfer[2]) > 0
                    drops = ns('iptables', '-nvx', '-L', 'INPUT').stdout.decode()
                    count = int(re.search(r'policy DROP (\d+) packets', drops).group(1)); assert count > 0
                    handshake.update({'observed': True, 'received_bytes': int(transfer[1]),
                                      'sent_bytes': int(transfer[2]), 'firewall_dropped_packets': count})
                    devices.revoke(tokens['device_id'])
                    assert WireGuardEnrollments(store).list()[0]['state'] == 'revoked'
                    push_private('wireguard-gate.txt', b'device-revoked')
                elif stage == 'device-revoked':
                    ns('wg', 'set', 'wg0', 'peer', client_public, 'remove')
                    assert not ns('wg', 'show', 'wg0', 'peers').stdout.strip()
                    push_private('wireguard-gate.txt', b'peer-removed')
                elif stage != 'disconnected': raise RuntimeError('Unknown instrumentation stage')
            checks.extend(instrument('network', callback))
            adb('shell', 'am', 'force-stop', PACKAGE)
            checks.extend(instrument('restart'))
            report = {'result': 'passed', 'provider': 'wireguard', 'api': int(adb('shell', 'getprop', 'ro.build.version.sdk').strip()),
                      'checks': checks, 'gateway_handshake': handshake, 'adb_reverse': False,
                      'tls': 'TLS 1.3, exact certificate and hostname validation', 'gateway': 'isolated Linux kernel WireGuard namespace',
                      'client': 'official embedded Android GoBackend', 'consent': 'actual system dialog, no appops bypass',
                      'private_profile_delivery': 'Android-generated private key never leaves app; public key enrolled over pinned LAN HTTPS',
                      'gateway_installation': 'disposable lab only; product installer and reconciliation not implemented',
                      'physical_nas': False, 'physical_tv': False, 'production_remote_access_enabled': False,
                      'apk_sha256': hashlib.sha256((ROOT/'connect/app/build/outputs/apk/debug/app-debug.apk').read_bytes()).hexdigest(),
                      'source_commit': command('git', '-C', ROOT, 'rev-parse', 'HEAD').stdout.decode().strip()}
            (OUT/'wireguard-network.json').write_text(json.dumps(report, indent=2)+'\n')
            print(json.dumps({'result': 'passed', 'api': report['api'], 'checks': len(checks)}))
        finally:
            if bootstrap:
                bootstrap.terminate()
                try: bootstrap.wait(timeout=5)
                except subprocess.TimeoutExpired: bootstrap.kill(); bootstrap.wait(timeout=5)
            if relay: relay.close()
            if created:
                raw = ip('netns', 'pids', namespace, check=False).stdout.decode().split()
                scoped = [p for p in raw if p.isdigit() and int(p) > 1]
                if scoped: command('sudo', 'kill', '-TERM', '--', *scoped, check=False)
                if server:
                    try: server.wait(timeout=5)
                    except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=5)
                ip('netns', 'delete', namespace, check=False)
            if link_created: ip('link', 'delete', host_link, check=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', type=Path)
    parser.add_argument('--check-services', type=Path)
    parser.add_argument('--bootstrap', type=Path)
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    if args.serve: serve(args.serve)
    elif args.check_services: check_services(args.check_services)
    elif args.bootstrap:
        assert args.port is not None and 1 <= args.port <= 65535
        serve(args.bootstrap, args.port)
    else: run()
