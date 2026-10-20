"""Install and update the non-debug release on a disposable rooted CI emulator.

This gate tests package/signing/update mechanics, separately from the debug
instrumentation's LAN/media journey. No production key enters CI.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'connect/test-results/distribution'
PACKAGE = 'com.novacinema.cinema'


def adb(*args, check=True):
    return subprocess.run(['adb', *map(str, args)], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, check=check, timeout=120)


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or adb('shell', 'getprop', 'ro.kernel.qemu').stdout.strip() != '1':
        raise SystemExit('Only a disposable GitHub Actions emulator is permitted')
    adb('root', check=False);adb('wait-for-device')
    assert adb('shell', 'id', '-u').stdout.strip() == '0'
    checks = []
    adb('install', str(OUT/'candidate.apk'))
    details = adb('shell', 'dumpsys', 'package', PACKAGE).stdout
    assert 'versionCode=9 ' in details
    assert adb('shell', 'run-as', PACKAGE, 'id', check=False).returncode != 0
    checks.append('release installed; run-as denied for non-debug application')
    adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
    adb('shell', 'wm', 'dismiss-keyguard')
    launch = adb('shell', 'am', 'start', '-W', '-n', PACKAGE+'/com.novacinema.connect.MainActivity').stdout
    assert 'Status: ok' in launch
    # Read actual rendered UI, not only process installation success.
    deadline = time.monotonic()+30
    while True:
        adb('shell', 'uiautomator', 'dump', '/sdcard/nova-release-window.xml')
        xml = adb('shell', 'cat', '/sdcard/nova-release-window.xml').stdout
        (OUT/'launcher.xml').write_text(xml)
        # The Directory button receives initial focus. ScrollView can therefore
        # put the title outside the viewport on a portrait emulator. Check the
        # focused entry and its real package; aapt checks the application label.
        if 'Entrar na NOVA' in xml and 'package="'+PACKAGE+'"' in xml:
            break
        assert time.monotonic() < deadline
        time.sleep(1)
    capture = subprocess.run(['adb', 'exec-out', 'screencap', '-p'], stdout=subprocess.PIPE, check=True, timeout=30)
    (OUT/'launcher.png').write_bytes(capture.stdout)
    checks.append('release launcher renders Directory entry in the distribution package')
    # Root is used only by the isolated harness to inspect sandbox preservation.
    # The product remains non-debuggable and contains no test data endpoints.
    marker = secrets.token_hex(32)
    marker_file = '/data/user/0/'+PACKAGE+'/files/distribution-update-marker'
    adb('shell', 'mkdir', '-p', '/data/user/0/'+PACKAGE+'/files')
    adb('shell', 'sh', '-c', '"printf '+marker+' > '+marker_file+'"')
    uid_before = adb('shell', 'stat', '-c', '%u', '/data/user/0/'+PACKAGE).stdout.strip()
    foreign = adb('install', '-r', str(OUT/'foreign.apk'), check=False)
    assert foreign.returncode != 0 and 'INSTALL_FAILED_UPDATE_INCOMPATIBLE' in foreign.stdout+foreign.stderr
    assert adb('shell', 'cat', marker_file).stdout == marker
    checks.append('foreign signing identity refused by Android; original sandbox retained')
    adb('install', '-r', str(OUT/'upgrade.apk'))
    assert 'versionCode=10 ' in adb('shell', 'dumpsys', 'package', PACKAGE).stdout
    assert adb('shell', 'stat', '-c', '%u', '/data/user/0/'+PACKAGE).stdout.strip() == uid_before
    assert adb('shell', 'cat', marker_file).stdout == marker
    assert adb('shell', 'run-as', PACKAGE, 'id', check=False).returncode != 0
    checks.append('higher version with same signer preserves sandbox and UID')
    downgrade = adb('install', '-r', str(OUT/'candidate.apk'), check=False)
    assert downgrade.returncode != 0 and 'INSTALL_FAILED_VERSION_DOWNGRADE' in downgrade.stdout+downgrade.stderr
    checks.append('version downgrade refused by Android')
    assert 'Status: ok' in adb('shell', 'am', 'start', '-W', '-n', PACKAGE+'/com.novacinema.connect.MainActivity').stdout
    checks.append('updated non-debug release launches')
    report = {'result': 'passed', 'api': int(adb('shell', 'getprop', 'ro.build.version.sdk').stdout.strip()),
              'checks': checks, 'physical_device': False,
              'candidate_sha256': hashlib.sha256((OUT/'candidate.apk').read_bytes()).hexdigest(),
              'upgrade_sha256': hashlib.sha256((OUT/'upgrade.apk').read_bytes()).hexdigest(),
              'signing_identity': 'disposable CI key; production key never uploaded'}
    (OUT/'android-distribution.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'result': 'passed', 'api': report['api'], 'checks': len(checks)}))


if __name__ == '__main__':
    main()
