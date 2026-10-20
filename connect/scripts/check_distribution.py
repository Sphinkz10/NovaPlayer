"""Exercise real SDK signing tools with disposable keys, never the release key."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT/'connect/scripts/distribution.py'


def run(args, *, succeeds=True):
    result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert (result.returncode == 0) == succeeds, result.stdout+result.stderr
    return json.loads(result.stdout) if succeeds else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--unsigned', type=Path, required=True)
    parser.add_argument('--upgrade', type=Path, required=True)
    parser.add_argument('--debug', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    original_password = secrets.token_urlsafe(48)
    os.environ['NOVA_SIGNING_PASSWORD'] = original_password
    checks = []
    with tempfile.TemporaryDirectory(prefix='nova-distribution-key-') as temp:
        base = Path(temp)
        owner = base/'owner';wrong = base/'wrong'
        owner_id = run(['create-key', '--output', owner])
        run(['create-key', '--output', owner], succeeds=False)
        wrong_id = run(['create-key', '--output', wrong])
        assert owner_id['certificate_sha256'] != wrong_id['certificate_sha256']
        checks.append('private identity creation is exclusive')
        common = ['--identity', owner/'identity.json', '--keystore', owner/'nova-cinema.p12']
        released = args.output/'candidate.apk';upgraded = args.output/'upgrade.apk'
        release = run(['sign', '--input', args.unsigned, '--output', released, *common])
        assert release['version_code'] == 9
        checks.append('release package, SDK, TV launcher, four ABIs, no debug, v2 signature and 16K ZIP alignment')
        run(['verify', '--apk', released, '--identity', owner/'identity.json'])
        checks.append('independent verification against certificate pin')
        run(['sign', '--input', args.unsigned, '--output', released, *common], succeeds=False)
        checks.append('existing output cannot be overwritten')
        run(['sign', '--input', args.debug, '--output', args.output/'debug-rejected.apk', *common], succeeds=False)
        checks.append('debug/laboratory package rejected')
        run(['sign', '--input', args.unsigned, '--output', args.output/'wrong-rejected.apk',
             '--identity', owner/'identity.json', '--keystore', wrong/'nova-cinema.p12'], succeeds=False)
        checks.append('private key mismatch rejected before signing')
        os.environ['NOVA_SIGNING_PASSWORD'] = 'wrong-password-that-is-long-enough'
        run(['sign', '--input', args.unsigned, '--output', args.output/'password-rejected.apk', *common], succeeds=False)
        # Both temporary stores use the initial password. Restore it for the
        # remaining real signing operations without printing it.
        os.environ['NOVA_SIGNING_PASSWORD'] = original_password
        checks.append('wrong keystore password rejected')
        run(['sign', '--input', args.unsigned, '--output', args.output/'rollback-rejected.apk',
             '--previous', released, *common], succeeds=False)
        checks.append('non-increasing versionCode rejected')
        upgrade = run(['sign', '--input', args.upgrade, '--output', upgraded, '--previous', released, *common])
        assert upgrade['version_code'] == 10 and upgrade['certificate_sha256'] == release['certificate_sha256']
        checks.append('next version signed by the same identity')
        altered = base/'altered.apk';data = bytearray(released.read_bytes());data[len(data)//2] ^= 1;altered.write_bytes(data)
        run(['verify', '--apk', altered, '--identity', owner/'identity.json'], succeeds=False)
        checks.append('modified signed APK rejected')
        foreign = run(['sign', '--input', args.upgrade, '--output', args.output/'foreign.apk',
                       '--identity', wrong/'identity.json', '--keystore', wrong/'nova-cinema.p12'])
        run(['verify', '--apk', args.output/'foreign.apk', '--identity', owner/'identity.json'], succeeds=False)
        checks.append('valid foreign signature rejected by pinned verifier')
        (args.output/'identity.json').write_text(json.dumps(owner_id, indent=2)+'\n')
    os.environ.pop('NOVA_SIGNING_PASSWORD', None)
    report = {'result': 'passed', 'purpose': 'disposable CI signing identity; not the distribution key',
              'checks': checks, 'candidate': release, 'upgrade': upgrade,
              'foreign_sha256': foreign['sha256'],
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    (args.output/'signing-gate.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'result': 'passed', 'checks': len(checks)}))


if __name__ == '__main__':
    main()
