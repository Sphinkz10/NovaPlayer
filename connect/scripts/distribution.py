"""Offline Android distribution. Private keys never belong in sources/artifacts.

Requires JDK keytool and Android SDK build tools 35+. Passwords are read only
from the named environment variable and passed to tools by environment name.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = 'com.novacinema.cinema'
ALIAS = 'nova-cinema-v1'


def invoke(command, *, check=True, binary=False):
    result = subprocess.run([str(x) for x in command], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=not binary)
    if check and result.returncode:
        # Tools can print parsed configuration. Do not copy their diagnostics
        # or credentials into distributable reports or console output.
        raise ValueError('Android signing tool failed: '+Path(str(command[0])).name)
    return result


def tool(args, name):
    if name == 'keytool':
        candidate = Path(os.environ.get('JAVA_HOME', ''))/'bin'/('keytool.exe' if os.name == 'nt' else 'keytool')
        if candidate.is_file():
            return candidate
        found = shutil.which(name)
        if found:
            return Path(found)
        raise ValueError('JDK keytool is required')
    base = args.build_tools
    if base is None:
        sdk = os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT')
        if not sdk:
            raise ValueError('Set ANDROID_HOME or --build-tools')
        base = Path(sdk)/'build-tools/35.0.0'
    suffix = ('.bat' if name == 'apksigner' else '.exe') if os.name == 'nt' else ''
    candidate = base/(name+suffix)
    if not candidate.is_file():
        raise ValueError('Missing Android build tool: '+name)
    return candidate


def password(name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError('Invalid password environment variable name')
    value = os.environ.get(name, '')
    if len(value) < 24 or '\n' in value or '\r' in value:
        raise ValueError('A password of at least 24 characters is required in the named environment variable')


def public_identity(der):
    return {'schema': 1, 'package': PACKAGE, 'alias': ALIAS,
            'certificate_sha256': hashlib.sha256(der).hexdigest(),
            'minimum_version_code': 9}


def secure_directory(path):
    path.mkdir(mode=0o700)
    if os.name == 'nt':
        row = next(csv.reader(invoke(['whoami', '/user', '/fo', 'csv', '/nh']).stdout.splitlines()))
        sid = row[1]
        if not re.fullmatch(r'S-1-(?:\d+-)*\d+', sid):
            raise ValueError('Cannot identify the Windows owner')
        invoke(['icacls', path, '/inheritance:r', '/grant:r',
                '*'+sid+':(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'])


def create_key(args):
    destination = args.output.resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError('Private signing keys must be created outside the repository')
    if destination.exists():
        raise ValueError('Refusing to replace an existing signing identity')
    password(args.password_env)
    secure_directory(destination)
    key = destination/'nova-cinema.p12'
    invoke([tool(args, 'keytool'), '-genkeypair', '-keystore', key,
            '-storetype', 'PKCS12', '-storepass:env', args.password_env,
            '-keypass:env', args.password_env, '-alias', ALIAS, '-keyalg', 'RSA',
            '-keysize', '3072', '-validity', '10000', '-dname', 'CN=NOVA Cinema', '-noprompt'])
    key.chmod(0o600)
    der = invoke([tool(args, 'keytool'), '-exportcert', '-keystore', key,
                  '-storepass:env', args.password_env, '-alias', ALIAS], binary=True).stdout
    identity = public_identity(der)
    (destination/'certificate.der').write_bytes(der)
    (destination/'identity.json').write_text(json.dumps(identity, indent=2)+'\n')
    print(json.dumps(identity))


def inspect(args, apk):
    badging = invoke([tool(args, 'aapt'), 'dump', 'badging', apk]).stdout
    package = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging, re.M)
    if not package or package[1] != PACKAGE:
        raise ValueError('Expected the NOVA Cinema distribution package')
    if 'application-debuggable' in badging or 'testOnly' in badging:
        raise ValueError('Debug/test APKs cannot be distributed')
    if "sdkVersion:'26'" not in badging or "application-label:'NOVA Cinema'" not in badging:
        raise ValueError('Unexpected distribution SDK or application name')
    native = re.search(r'^native-code: (.+)$', badging, re.M)
    if not native or set(re.findall(r"'([^']+)'", native[1])) != {'arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'}:
        raise ValueError('Expected the four supported Android ABIs')
    if "leanback-launchable-activity: name='com.novacinema.connect.MainActivity'" not in badging:
        raise ValueError('TV launcher is required')
    return {'package': package[1], 'version_code': int(package[2]), 'version_name': package[3],
            'debuggable': False, 'min_sdk': 26, 'abis': sorted(re.findall(r"'([^']+)'", native[1]))}


def verify(args, apk, expected):
    result = invoke([tool(args, 'apksigner'), 'verify', '--verbose', '--print-certs', apk]).stdout
    fingerprints = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)$', result, re.M)
    if fingerprints != [expected['certificate_sha256']]:
        raise ValueError('APK signer differs from the pinned distribution identity')
    if 'Verified using v2 scheme (APK Signature Scheme v2): true' not in result:
        raise ValueError('APK Signature Scheme v2 is required')
    invoke([tool(args, 'zipalign'), '-c', '-P', '16', '4', apk])
    metadata = inspect(args, apk)
    if metadata['version_code'] < expected['minimum_version_code']:
        raise ValueError('Distribution version predates the pinned identity')
    return {**metadata, 'certificate_sha256': fingerprints[0], 'signature_v2': True,
            'zip_alignment_16k': True, 'sha256': hashlib.sha256(apk.read_bytes()).hexdigest()}


def identity(path):
    value = json.loads(path.read_text())
    if set(value) != {'schema', 'package', 'alias', 'certificate_sha256', 'minimum_version_code'} or \
            value['schema'] != 1 or value['package'] != PACKAGE or value['alias'] != ALIAS or \
            type(value['minimum_version_code']) is not int or value['minimum_version_code'] < 9 or \
            not re.fullmatch(r'[0-9a-f]{64}', value['certificate_sha256']):
        raise ValueError('Invalid public distribution identity')
    return value


def sign(args):
    expected = identity(args.identity)
    password(args.password_env)
    if args.output.exists() or args.output.with_suffix('.json').exists():
        raise ValueError('Refusing to replace an existing APK or report')
    metadata = inspect(args, args.input)
    if invoke([tool(args, 'apksigner'), 'verify', args.input], check=False).returncode == 0:
        raise ValueError('Expected an unsigned APK from the verified build')
    der = invoke([tool(args, 'keytool'), '-exportcert', '-keystore', args.keystore,
                  '-storepass:env', args.password_env, '-alias', ALIAS], binary=True).stdout
    if public_identity(der)['certificate_sha256'] != expected['certificate_sha256']:
        raise ValueError('Private key differs from the pinned distribution identity')
    if args.previous:
        previous = verify(args, args.previous, expected)
        if metadata['version_code'] <= previous['version_code']:
            raise ValueError('Updates require a strictly greater versionCode')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nova-sign-', dir=args.output.parent) as temp:
        signed = Path(temp)/'signed.apk'
        invoke([tool(args, 'apksigner'), 'sign', '--ks', args.keystore, '--ks-key-alias', ALIAS,
                '--ks-pass', 'env:'+args.password_env, '--key-pass', 'env:'+args.password_env,
                '--v1-signing-enabled', 'false', '--v2-signing-enabled', 'true',
                '--v3-signing-enabled', 'true', '--v4-signing-enabled', 'false',
                '--out', signed, args.input])
        report = verify(args, signed, expected)
        report.update({'unsigned_sha256': hashlib.sha256(args.input.read_bytes()).hexdigest(),
                       'result': 'passed', 'previous_sha256': previous['sha256'] if args.previous else None})
        with args.output.open('xb') as target:
            target.write(signed.read_bytes())
        with args.output.with_suffix('.json').open('x') as target:
            json.dump(report, target, indent=2);target.write('\n')
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-tools', type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create-key')
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--password-env', default='NOVA_SIGNING_PASSWORD')
    signing = commands.add_parser('sign')
    signing.add_argument('--input', type=Path, required=True)
    signing.add_argument('--output', type=Path, required=True)
    signing.add_argument('--keystore', type=Path, required=True)
    signing.add_argument('--password-env', default='NOVA_SIGNING_PASSWORD')
    signing.add_argument('--previous', type=Path)
    for command in (signing, commands.add_parser('verify')):
        command.add_argument('--identity', type=Path, default=ROOT/'connect/release-identity.json')
    commands.choices['verify'].add_argument('--apk', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'create-key':
            create_key(args)
        elif args.command == 'sign':
            sign(args)
        else:
            print(json.dumps(verify(args, args.apk, identity(args.identity))))
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise SystemExit(str(error)) from None


if __name__ == '__main__':
    main()
