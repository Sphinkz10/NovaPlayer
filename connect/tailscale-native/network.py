"""Disposable emulator + real libtailscale + isolated Linux peer + NOVA HTTPS.

Headscale is a test coordinator, not a claim of testing a user's Tailscale SaaS
account. No host route to the overlay, TCP proxy, adb reverse or external VPN app.
Only encrypted Tailscale traffic can reach the namespace's HTTPS service.
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
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'connect/test-results/tailscale'
PACKAGE = 'com.novacinema.connect.poc'
GATEWAY = '100.64.0.1'
CONTROL = 'https://10.0.2.2:18443'
sys.path.insert(0, str(ROOT/'server'))


def command(*args, data=None, check=True, timeout=40, env=None):
    result = subprocess.run(list(map(str, args)), input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, env=env)
    if check and result.returncode:
        # Commands may contain a disposable auth key. Never put args/output into errors.
        raise RuntimeError('Test command failed: '+Path(str(args[0])).name)
    return result


def adb(*args, **kwargs):
    return command('adb', *args, **kwargs).stdout.decode(errors='replace')


def push(name, data):
    assert name in ('tailscale-fixture.json', 'tailscale-gate.txt')
    command('adb', 'shell', '-T', 'run-as', PACKAGE, 'tee', 'files/'+name, data=data)


def certificate(root, name, addresses):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'NOVA disposable Tailscale proof')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=2))
            .not_valid_after(now+timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip)) for ip in addresses]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False).sign(key, hashes.SHA256()))
    pem = cert.public_bytes(serialization.Encoding.PEM)
    (root/(name+'.crt')).write_bytes(pem)
    private = root/(name+'.key')
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption())); private.chmod(0o600)
    return pem.decode('ascii')


def tools(root):
    artifacts = (
        ('headscale', 'https://github.com/juanfont/headscale/releases/download/v0.29.5/headscale_0.29.5_linux_amd64',
         'e979d27fe17d924d33bb6ab7504f6338d0635989a0cfdcfbc0ceb637dbcbe980'),
        ('tailscale.tgz', 'https://pkgs.tailscale.com/stable/tailscale_1.104.2_amd64.tgz',
         '512f613ed7d04fc7282f7dc5bd76aa105aae28168fbb9357eb749ebcbc29f0ae'))
    for name, url, digest in artifacts:
        with urllib.request.urlopen(url, timeout=90) as source:
            raw = source.read(150_000_001)
        assert len(raw) <= 150_000_000 and hashlib.sha256(raw).hexdigest() == digest
        (root/name).write_bytes(raw)
    (root/'headscale').chmod(0o700)
    with tarfile.open(root/'tailscale.tgz') as archive:
        for binary in ('tailscale', 'tailscaled'):
            members = [item for item in archive.getmembers() if item.isfile() and Path(item.name).name == binary]
            assert len(members) == 1 and members[0].size < 100_000_000
            (root/binary).write_bytes(archive.extractfile(members[0]).read()); (root/binary).chmod(0o700)


def serve(root):
    import uvicorn
    from nova_server.client_api import make_client_app
    def canary(port):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('0.0.0.0', port)); listener.listen()
            while True:
                connection, _ = listener.accept(); connection.close()
    for port in (22, 9443): threading.Thread(target=canary, args=(port,), daemon=True).start()
    config = uvicorn.Config(make_client_app(root/'state', 'https://'+GATEWAY+':9444'), host=GATEWAY, port=9444,
                            ssl_certfile=str(root/'gateway.crt'), ssl_keyfile=str(root/'gateway.key'),
                            log_level='error', access_log=False, proxy_headers=False)
    config.load(); config.ssl.minimum_version = ssl.TLSVersion.TLSv1_3
    uvicorn.Server(config).run()


def consent():
    deadline = time.monotonic()+25
    while time.monotonic() < deadline:
        adb('shell', 'uiautomator', 'dump', '/sdcard/nova-ts-consent.xml')
        xml = adb('shell', 'cat', '/sdcard/nova-ts-consent.xml')
        nodes = [node for node in ET.fromstring(xml).iter('node') if node.get('package') == 'com.android.vpndialogs'
                 and node.get('resource-id') == 'android:id/button1' and node.get('enabled') == 'true']
        if nodes:
            bounds = list(map(int, re.findall(r'\d+', nodes[0].get('bounds', '')))); assert len(bounds) == 4
            (OUT/'android-vpn-consent.xml').write_text(xml)
            adb('shell', 'input', 'tap', str((bounds[0]+bounds[2])//2), str((bounds[1]+bounds[3])//2)); return
        time.sleep(.25)
    raise RuntimeError('Actual Android VPN consent dialog not observed')


def instrument(mode, callback):
    process = subprocess.Popen(['adb', 'shell', 'am', 'instrument', '-w', '-r', '-e', 'mode', mode,
        PACKAGE+'.test/com.novacinema.connect.TailscaleNetworkInstrumentation'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    timer = threading.Timer(300, process.kill); timer.start(); lines = []
    try:
        for line in process.stdout:
            lines.append(line)
            stage = re.search(r'INSTRUMENTATION_STATUS: tailscale_stage=([a-z-]+)', line)
            if stage: callback(stage[1])
        process.wait(timeout=10)
    finally:
        timer.cancel()
        if process.poll() is None: process.kill(); process.wait(timeout=10)
    output = ''.join(lines); (OUT/(mode+'.txt')).write_text(output)
    assert 'INSTRUMENTATION_RESULT: nova_tailscale=passed' in output, 'Android proof failed; inspect '+mode+'.txt'
    assert 'INSTRUMENTATION_CODE: -1' in output
    return output


def run():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or sys.platform != 'linux':
        raise SystemExit('Scoped to a disposable Linux GitHub runner.')
    if adb('shell', 'getprop', 'ro.kernel.qemu').strip() != '1':
        raise SystemExit('Refusing a physical device.')
    OUT.mkdir(parents=True, exist_ok=True)
    for apk in ('debug/app-debug.apk', 'androidTest/debug/app-debug-androidTest.apk'):
        adb('install', '-r', '-t', str(ROOT/'connect/app/build/outputs/apk'/apk), timeout=180)
    # Create the app's private files directory before run-as receives the fixture.
    adb('shell', 'am', 'start', '-n', PACKAGE+'/com.novacinema.connect.MainActivity')
    adb('shell', 'run-as', PACKAGE, 'mkdir', '-p', 'files')
    checks = []; processes = []; handles = []
    namespace = 'nova-ts-'+uuid.uuid4().hex[:8]; host_link = 'nt'+uuid.uuid4().hex[:8]; peer_link = 'np'+uuid.uuid4().hex[:8]
    with tempfile.TemporaryDirectory(prefix='nova-tailscale-') as temporary:
        root = Path(temporary).resolve(); assert root.parent == Path(tempfile.gettempdir()).resolve()
        ip = lambda *args, **kw: command('sudo', 'ip', *args, **kw)
        ns = lambda *args, **kw: ip('netns', 'exec', namespace, *args, **kw)
        def spawn(args, name, env=None):
            handle = (root/(name+'.log')).open('wb'); handles.append(handle)
            process = subprocess.Popen(list(map(str, args)), stdout=handle, stderr=subprocess.STDOUT, env=env)
            processes.append(process); return process
        try:
            tools(root)
            control_ca = certificate(root, 'control', ['10.0.2.2', '127.0.0.1', '10.203.0.1'])
            gateway_ca = certificate(root, 'gateway', [GATEWAY])
            wrong = certificate(root, 'wrong', [GATEWAY])
            config = {
                'server_url': CONTROL, 'listen_addr': '0.0.0.0:18443', 'metrics_listen_addr': '127.0.0.1:19090',
                'grpc_listen_addr': '127.0.0.1:15443', 'unix_socket': str(root/'headscale.sock'),
                'noise': {'private_key_path': str(root/'noise.key')},
                'prefixes': {'v4': '100.64.0.0/24', 'v6': 'fd7a:115c:a1e0::/48', 'allocation': 'sequential'},
                'database': {'type': 'sqlite', 'sqlite': {'path': str(root/'headscale.sqlite'), 'write_ahead_log': True}},
                'tls_cert_path': str(root/'control.crt'), 'tls_key_path': str(root/'control.key'),
                'derp': {'server': {'enabled': True, 'region_id': 999, 'region_code': 'nova-lab',
                    'region_name': 'NOVA disposable lab', 'verify_clients': True, 'stun_listen_addr': '0.0.0.0:3478',
                    'private_key_path': str(root/'derp.key'), 'automatically_add_embedded_derp_region': True,
                    'ipv4': '10.0.2.2'}, 'urls': [], 'auto_update_enabled': False},
                'dns': {'magic_dns': False, 'base_domain': 'nova.invalid', 'override_local_dns': False,
                        'nameservers': {'global': [], 'split': {}}},
                'log': {'level': 'error', 'format': 'text'}, 'disable_check_updates': True,
                'policy': {'mode': 'file', 'path': str(root/'policy.json')}}
            (root/'policy.json').write_text(json.dumps({'acls': [{'action': 'accept', 'src': ['*'], 'dst': [GATEWAY+':9444']}]}))
            (root/'config.json').write_text(json.dumps(config))
            hs = lambda *args, **kw: command(root/'headscale', '--config', root/'config.json', *args, **kw)
            headscale = spawn([root/'headscale', '--config', root/'config.json', 'serve'], 'headscale')
            for _ in range(100):
                if headscale.poll() is not None: raise RuntimeError('Headscale exited')
                if hs('users', 'list', '-o', 'json', check=False).returncode == 0: break
                time.sleep(.2)
            else: raise RuntimeError('Headscale not ready')
            user = json.loads(hs('users', 'create', 'nova-proof', '-o', 'json').stdout)
            def authkey():
                return json.loads(hs('preauthkeys', 'create', '--user', str(user['id']), '--expiration', '10m', '-o', 'json').stdout)['key']
            peer_key, android_key = authkey(), authkey()
            ip('netns', 'add', namespace)
            ip('link', 'add', host_link, 'type', 'veth', 'peer', 'name', peer_link)
            ip('link', 'set', peer_link, 'netns', namespace)
            ip('addr', 'add', '10.203.0.1/30', 'dev', host_link)
            ip('addr', 'add', '10.0.2.2/32', 'dev', host_link)
            ip('link', 'set', host_link, 'up')
            ns('ip', 'addr', 'add', '10.203.0.2/30', 'dev', peer_link)
            ns('ip', 'link', 'set', peer_link, 'up'); ns('ip', 'link', 'set', 'lo', 'up')
            ns('ip', 'route', 'add', '10.0.2.2/32', 'via', '10.203.0.1')
            daemon = spawn(['sudo', 'ip', 'netns', 'exec', namespace, 'env', 'SSL_CERT_FILE='+str(root/'control.crt'),
                'TS_NO_LOGS_NO_SUPPORT=1', root/'tailscaled', '--tun=tailscale0', '--port=41641',
                '--state='+str(root/'tailscale.state'), '--socket='+str(root/'tailscale.sock')], 'tailscaled')
            ts = lambda *args, **kw: ns(root/'tailscale', '--socket='+str(root/'tailscale.sock'), *args, **kw)
            for _ in range(100):
                if daemon.poll() is not None: raise RuntimeError('Linux Tailscale daemon exited')
                if (root/'tailscale.sock').exists(): break
                time.sleep(.2)
            ts('up', '--login-server='+CONTROL, '--auth-key='+peer_key, '--accept-dns=false', '--accept-routes=false',
               '--hostname=nova-gateway', '--netfilter-mode=off', '--timeout=60s', timeout=80)
            assert ts('ip', '-4').stdout.decode().strip() == GATEWAY
            checks.append('pinned real Linux Tailscale peer enrolled with a one-use ten-minute key')
            # Never let the runner route directly to a tail address.
            host_route = json.loads(ip('-j', 'route', 'get', GATEWAY).stdout)[0]
            assert host_route.get('dev') != host_link and host_route.get('gateway') != '10.203.0.2'
            checks.append('host has no overlay route or TCP proxy to NOVA')
            ns('sysctl', '-q', '-w', 'net.ipv4.ip_forward=0')
            ns('iptables', '-P', 'FORWARD', 'DROP'); ns('iptables', '-P', 'INPUT', 'DROP')
            ns('iptables', '-A', 'INPUT', '-i', 'lo', '-j', 'ACCEPT')
            ns('iptables', '-A', 'INPUT', '-i', 'tailscale0', '-p', 'tcp', '--dport', '9444', '-j', 'ACCEPT')
            ns('iptables', '-A', 'INPUT', '-i', 'tailscale0', '-j', 'DROP')
            ns('iptables', '-A', 'INPUT', '-p', 'udp', '--dport', '41641', '-j', 'ACCEPT')
            ns('iptables', '-A', 'INPUT', '-m', 'conntrack', '--ctstate', 'ESTABLISHED,RELATED', '-j', 'ACCEPT')
            from nova_server.storage import Store
            from nova_server.devices import Devices
            from nova_server.security import hash_password
            store = Store(root/'state'); assert store.bootstrap('owner', hash_password(secrets.token_urlsafe(32)))
            devices = Devices(store); grant = devices.start('NOVA Tailscale disposable emulator')
            pending = devices.inspect(grant['user_code']); devices.decide(grant['user_code'], pending['request_id'], True)
            tokens = devices.poll(grant['device_code'])
            spawn(['sudo', 'ip', 'netns', 'exec', namespace, sys.executable, Path(__file__).resolve(), '--serve', root], 'nova')
            for _ in range(100):
                probe = ns(sys.executable, '-c', "import socket;s=socket.create_connection(('100.64.0.1',9444),1);s.close()", check=False)
                if probe.returncode == 0: break
                time.sleep(.2)
            else: raise RuntimeError('NOVA HTTPS not ready')
            for port in (22, 9443):
                ns(sys.executable, '-c', f"import socket;s=socket.create_connection(('127.0.0.1',{port}),1);s.close()")
            checks.append('real NOVA Core HTTPS and live blocked administration/SSH canaries')
            fixture = {'control': CONTROL, 'control_ca': control_ca, 'gateway': GATEWAY, 'auth_key': android_key,
                       'certificate_pem': gateway_ca, 'wrong_certificate_pem': wrong,
                       'server_id': devices.identity(), 'device_id': tokens['device_id'], 'access_token': tokens['access_token']}
            push('tailscale-fixture.json', json.dumps(fixture).encode())
            def callback(stage):
                if stage == 'consent': consent()
                elif stage == 'revoke':
                    assert devices.authenticate(tokens['access_token'])['device_id'] == tokens['device_id']
                    nodes = json.loads(hs('nodes', 'list', '-o', 'json').stdout)
                    android = [node for node in nodes if GATEWAY not in node['ip_addresses']]
                    assert len(android) == 1
                    hs('nodes', 'expire', '--identifier', str(android[0]['id']))
                    push('tailscale-gate.txt', b'revoked')
                else: raise RuntimeError('Unknown Android test stage')
            first = instrument('network', callback)
            key_match = re.search(r'INSTRUMENTATION_RESULT: node_key=(nodekey:[a-f0-9]+)', first); assert key_match
            adb('shell', 'am', 'force-stop', PACKAGE)
            prefs = adb('shell', 'run-as', PACKAGE, 'cat', 'shared_prefs/nova_tailscale_state.xml')
            assert 'privkey:' not in prefs and android_key not in prefs and tokens['access_token'] not in prefs
            checks.append('persisted identity sealed with Android Keystore; no enrollment key or NOVA token in engine preferences')
            fixture.pop('auth_key'); fixture['expected_node_key'] = key_match[1]
            push('tailscale-fixture.json', json.dumps(fixture).encode())
            instrument('restart', callback)
            assert devices.authenticate(tokens['access_token'])['device_id'] == tokens['device_id']
            checks.append('overlay revocation proven while NOVA access credential remains valid')
            adb('shell', 'am', 'force-stop', PACKAGE)
            # Corrupt one authenticated preference while the service process is stopped.
            document = ET.fromstring(adb('shell', 'run-as', PACKAGE, 'cat', 'shared_prefs/nova_tailscale_state.xml'))
            entry = next(item for item in document if item.tag == 'string')
            original = entry.text; assert original and len(original) > 32
            entry.text = ('A' if original[0] != 'A' else 'B')+original[1:]
            damaged = ET.tostring(document, encoding='utf-8', xml_declaration=True)
            command('adb', 'shell', '-T', 'run-as', PACKAGE, 'tee', 'shared_prefs/nova_tailscale_state.xml', data=damaged)
            instrument('tamper', callback)
            after = adb('shell', 'run-as', PACKAGE, 'cat', 'shared_prefs/nova_tailscale_state.xml')
            assert entry.text in after
            checks.append('corrupted state remains corrupted after refusal, without silently replacing identity')
            adb('shell', 'am', 'force-stop', PACKAGE)
            entry.text = original
            restored = ET.tostring(document, encoding='utf-8', xml_declaration=True)
            command('adb', 'shell', '-T', 'run-as', PACKAGE, 'tee', 'shared_prefs/nova_tailscale_state.xml', data=restored)
            instrument('missing-key', callback)
            after_missing = adb('shell', 'run-as', PACKAGE, 'cat', 'shared_prefs/nova_tailscale_state.xml')
            assert original in after_missing
            checks.append('sealed identity preserved when its missing Android wrapping key is refused')
            outputs = [(OUT/(mode+'.txt')).read_text() for mode in ('network', 'restart', 'tamper', 'missing-key')]
            count = sum(int(re.search(r'INSTRUMENTATION_RESULT: checks_count=(\d+)', output)[1]) for output in outputs)
            report = {'result': 'passed', 'provider': 'tailscale', 'api': int(adb('shell', 'getprop', 'ro.build.version.sdk')),
                'android_checks': count, 'harness_checks': checks, 'native_engine_aar_sha256':
                '224bfc4ef95c9c173f1a2d62a377f129333313c1cb622b4d229cf37b6403e0a0',
                'coordinator': 'Headscale 0.29.5, disposable TLS coordinator', 'linux_peer': 'Tailscale 1.104.2',
                'source_commit': command('git', '-C', ROOT, 'rev-parse', 'HEAD').stdout.decode().strip(),
                'apk_sha256': hashlib.sha256((ROOT/'connect/app/build/outputs/apk/debug/app-debug.apk').read_bytes()).hexdigest(),
                'external_android_vpn_app': False, 'adb_reverse': False, 'physical_nas': False, 'physical_tv': False,
                'tailscale_saas_account': False, 'production_provider_enabled': False, 'media_playback_tested': False}
            (OUT/'tailscale-network.json').write_text(json.dumps(report, indent=2)+'\n')
            print(json.dumps({'result': 'passed', 'api': report['api'], 'android_checks': count, 'harness_checks': len(checks)}))
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    command('sudo', 'kill', '-TERM', str(process.pid), check=False)
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        command('sudo', 'kill', '-KILL', str(process.pid), check=False); process.wait(timeout=10)
            for handle in handles: handle.close()
            # Error-level logs only; redact any disposable fixture credentials before export.
            available = locals()
            secret_values = [available[name] for name in ('peer_key', 'android_key') if name in available]
            if 'tokens' in locals(): secret_values.extend((tokens['access_token'], tokens['refresh_token']))
            for name in ('headscale', 'tailscaled', 'nova'):
                file = root/(name+'.log')
                if file.exists():
                    value = file.read_text(errors='replace')
                    for secret in secret_values: value = value.replace(secret, '[redacted]')
                    value = re.sub(r'https?://\S*(?:auth|login|register)\S*', '[redacted-auth-url]', value)
                    (OUT/(name+'.log')).write_text(value[-60000:])
            crash = adb('logcat', '-d', '-b', 'crash')
            for secret in secret_values: crash = crash.replace(secret, '[redacted]')
            (OUT/'crash.txt').write_text(crash[-20000:])
            ip('netns', 'delete', namespace, check=False); ip('link', 'delete', host_link, check=False)
            command('sudo', 'chown', '-R', str(os.getuid())+':'+str(os.getgid()), str(root), check=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--serve', type=Path); args = parser.parse_args()
    if args.serve: serve(args.serve)
    else: run()
