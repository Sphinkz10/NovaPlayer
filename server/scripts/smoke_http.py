#!/usr/bin/env python3
"""Run one real loopback HTTP smoke test with a throwaway NOVA Core state."""
from __future__ import annotations
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT=18787
BASE=f'http://127.0.0.1:{PORT}'

def get(path):
    with urllib.request.urlopen(BASE+path,timeout=2) as r:
        return json.load(r)

def post(path, payload, headers=None):
    req=urllib.request.Request(BASE+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json',**(headers or {})},method='POST')
    with urllib.request.urlopen(req,timeout=5) as r:
        return json.load(r)

def run():
    with tempfile.TemporaryDirectory() as state:
        Path(state,'bootstrap.token').write_text('smoke-'+('a'*60))
        env={**os.environ,'NOVA_STATE_DIR':state,'NOVA_JELLYFIN_URL':'http://127.0.0.1:19999'}
        proc=subprocess.Popen([sys.executable,'-m','uvicorn','nova_server.app:app','--host','127.0.0.1','--port',str(PORT),'--no-proxy-headers','--no-access-log'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    if get('/api/v1/health/live')['status']=='up':break
                except (urllib.error.URLError,ValueError):time.sleep(.1)
            else:raise RuntimeError('Servidor não arrancou')
            assert get('/api/v1/status')['owner_setup_required']
            pw='smoke-strong-owner-secret-passphrase'
            r=post('/api/v1/admin/bootstrap',{'username':'owner','password':pw}, {'X-NOVA-Bootstrap':'smoke-'+('a'*60)})
            assert r['ok'] and not Path(state,'bootstrap.token').exists()
            assert not get('/api/v1/status')['owner_setup_required']
            auth=post('/api/v1/admin/login',{'username':'owner','password':pw})
            req=urllib.request.Request(BASE+'/api/v1/admin/overview',headers={'Authorization':'Bearer '+auth['access_token']})
            with urllib.request.urlopen(req,timeout=7) as x: overview=json.load(x)
            assert overview['nova_core']=='running'
            assert overview['jellyfin']['state']=='offline'
            assert overview['connect']['state']=='disabled'
            assert len(overview['library_roots'])==2
            assert all(x['read_only'] for x in overview['library_roots'])
            print('PASS real HTTP loopback: health → bootstrap → login → overview → offline Jellyfin (fail closed)')
        finally:
            proc.terminate()
            try:proc.wait(timeout=4)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)

if __name__=='__main__':run()
