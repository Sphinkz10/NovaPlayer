"""Generate/verify the current source inventory; excludes secrets and build output via Git.

Use --write to regenerate after changes. Without it, verify every recorded hash.
Historical manifests in archives/inventory-original remain immutable evidence.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT/'docs/INVENTARIO.json'
MANIFEST = ROOT/'docs/MANIFESTO_SHA256.txt'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(write=False):
    if write:
        result = subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],
                                cwd=ROOT, check=True, stdout=subprocess.PIPE)
        paths = sorted(set(result.stdout.decode('utf8').rstrip('\0').split('\0')))
        files = [{'path':name, 'bytes':(ROOT/name).stat().st_size, 'sha256':digest(ROOT/name)}
                 for name in paths if (ROOT/name).is_file() and (ROOT/name) not in (INVENTORY, MANIFEST)]
        INVENTORY.write_text(json.dumps({'schema_version':2, 'package':'NOVA-foundation-phase1',
            'base_commit':'57391fcc64e9e65220d6ed59f02dfa98f052db38',
            'excluded':['docs/INVENTARIO.json','docs/MANIFESTO_SHA256.txt','Git-ignored build/runtime files'],
            'files':files}, indent=2, ensure_ascii=False)+'\n', encoding='utf8', newline='\n')
        MANIFEST.write_text(''.join(f"{entry['sha256']}  {entry['path']}\n" for entry in files), encoding='utf8', newline='\n')
    entries = json.loads(INVENTORY.read_text(encoding='utf8'))['files']
    for entry in entries:
        path = ROOT/entry['path']
        if not path.is_file() or digest(path) != entry['sha256']:
            raise SystemExit('Inventory mismatch: '+entry['path'])
    print(f'PASS: {len(entries)} source files match the current inventory')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true')
    run(parser.parse_args().write)
