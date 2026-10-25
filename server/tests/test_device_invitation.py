import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from nova_server.storage import Store
from scripts.device_invitation import export


@pytest.fixture
def invitation_inputs(tmp_path):
    store = Store(tmp_path/'state'); store.bootstrap('owner','test-hash')
    openssl = shutil.which('openssl') or r'C:\Program Files\Git\usr\bin\openssl.exe'
    certificate, key = tmp_path/'cert.pem', tmp_path/'key.pem'
    subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=test',
                    '-addext','subjectAltName=IP:127.0.0.1','-keyout',str(key),'-out',str(certificate)],
                   check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return store, certificate, key


def test_export_is_public_requires_separate_fingerprint_and_no_overwrite(invitation_inputs,tmp_path):
    store,cert,key = invitation_inputs
    output = tmp_path/'invitation.json'
    result = export(store.dir,'https://127.0.0.1:8920',cert,output,now=1000)
    payload = json.loads(output.read_bytes())
    assert result['sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert result['requires_owner_approval'] and payload['expires_at'] == 87400
    assert key.read_text() not in output.read_text() and 'PRIVATE KEY' not in output.read_text()
    with pytest.raises(FileExistsError):
        export(store.dir,'https://127.0.0.1:8920',cert,output)


def test_export_rejects_private_key_and_public_or_ambiguous_origins(invitation_inputs,tmp_path):
    store,cert,key = invitation_inputs
    output = tmp_path/'invitation.json'
    with pytest.raises(ValueError):
        export(store.dir,'https://127.0.0.1:8920',key,output)
    for origin in ('http://127.0.0.1:8920','https://example.org:443','https://8.8.8.8:443',
                   'https://127.0.0.1:8920/path','https://127.0.0.1','https://user@127.0.0.1:8920',
                   ' https://127.0.0.1:8920','https://127.0.0.1:8920#x'):
        with pytest.raises(ValueError):
            export(store.dir,origin,cert,output)
    assert not output.exists()
