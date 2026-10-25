"""Package exactly the verified source inventory, never a recursive workspace dump."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from inventory import ROOT, INVENTORY, MANIFEST, run


def package(destination: Path):
    run()  # Refuse stale or modified source files.
    paths = [ROOT/entry['path'] for entry in json.loads(INVENTORY.read_text(encoding='utf8'))['files']]
    paths.extend((INVENTORY, MANIFEST))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, 'NOVA_Fase1/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(paths)
    print(f'{destination.name}: {len(paths)} files; SHA256 {hashlib.sha256(destination.read_bytes()).hexdigest()}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    package(parser.parse_args().destination)
