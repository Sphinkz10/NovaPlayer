"""Real browser -> owner Control -> TLS 1.3 Directory, with disposable state only."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile

import httpx
from playwright.sync_api import sync_playwright, expect

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
from nova_directory.store import Registry
from nova_server.security import hash_password
from nova_server.storage import Store
from smoke_devices_tls import free_port, stop, ready
from smoke_directory_tls import make_certificate


def run(output=None, channel=None):
    with tempfile.TemporaryDirectory(prefix='nova-directory-control-') as folder:
        root=Path(folder); cert,key=make_certificate(root)
        ports=set()
        while len(ports)<2: ports.add(free_port())
        admin_port,directory_port=sorted(ports)
        origin=f'https://127.0.0.1:{directory_port}'; base=f'http://127.0.0.1:{admin_port}'
        registry=Registry(root/'directory',origin)
        password=secrets.token_urlsafe(32); owner_password=secrets.token_urlsafe(32)
        registry.create_account('owner',password); registry.create_account('another',password)
        store=Store(root/'nova'); store.bootstrap('novaowner',hash_password(owner_password))
        processes=[]
        env={**os.environ,'NOVA_STATE_DIR':str(store.dir),'NOVA_JELLYFIN_URL':'http://127.0.0.1:1',
             'NOVA_DIRECTORY_ORIGIN':origin,'NOVA_DIRECTORY_CA':str(cert),
             'NOVA_CLIENT_ORIGIN':'https://127.0.0.1:8920','NOVA_CLIENT_CERT':str(cert)}
        def launch(command):
            process=subprocess.Popen([sys.executable,*command],cwd=SERVER,env=env,
                                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            processes.append(process);return process
        def start_admin():
            return launch(['-m','uvicorn','nova_server.app:app','--host','127.0.0.1','--port',str(admin_port),
                           '--no-proxy-headers','--no-access-log'])
        try:
            launch(['-m','nova_directory','serve','--state',str(root/'directory'),'--origin',origin,
                    '--certificate',str(cert),'--key',str(key)])
            admin=start_admin()
            with httpx.Client(base_url=base,trust_env=False,timeout=5) as probe:
                ready(probe,'/api/v1/health/live',admin,200)
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(headless=True,**({'channel':channel} if channel else {}))
                try:
                    page=browser.new_page(viewport={'width':1280,'height':1100}); errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    def login():
                        page.locator('#login [name=username]').fill('novaowner')
                        page.locator('#login [name=password]').fill(owner_password)
                        page.locator('#login button').click()
                        expect(page.locator('#ownerPanel')).to_be_visible()
                        page.locator('.sidebar nav [data-page=directory]').click()
                        expect(page.locator('#directoryActions')).to_be_visible()
                    def directory_password(username='owner',value=None):
                        page.locator('[name=directory_username]').fill(username)
                        page.locator('[name=directory_password]').fill(password if value is None else value)
                    page.goto(base);login()
                    expect(page.locator('#directoryForm button[type=submit]')).to_be_disabled()
                    page.locator('#directoryIdentity').click()
                    expect(page.locator('#directoryMessage')).to_contain_text('Identidade inicializada')
                    page.locator('[name=directory_name]').fill('Casa <img src=x onerror=alert(1)>')
                    directory_password(value='disposable-wrong-password')
                    page.locator('#directoryForm button[type=submit]').click()
                    expect(page.locator('#directoryMessage')).to_contain_text('Operação recusada')
                    expect(page.locator('[name=directory_password]')).to_have_value('')
                    directory_password()
                    page.locator('#directoryForm button[type=submit]').click()
                    expect(page.locator('#directoryMessage')).to_contain_text('Publicação aceite')
                    expect(page.locator('[name=directory_password]')).to_have_value('')
                    assert page.locator('#directoryPanel img').count()==0
                    directory_password();page.locator('#directoryForm button[type=submit]').click()
                    expect(page.locator('#directoryMessage')).to_contain_text('Publicação aceite')
                    with registry.db() as db:
                        assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
                    with page.expect_request('**/api/v1/admin/directory/renew') as renewal:
                        page.locator('#directoryRenew').click()
                    assert not renewal.value.post_data
                    expect(page.locator('#directoryMessage')).to_contain_text('Renovação confirmada sem palavra-passe')
                    directory_password();page.locator('#directoryCheck').click()
                    expect(page.locator('#directoryStatus')).to_contain_text('Encontrado na última verificação')
                    directory_password('another');page.locator('#directoryCheck').click()
                    expect(page.locator('#directoryMessage')).to_contain_text('originalmente associada')
                    expect(page.locator('[name=directory_password]')).to_have_value('')
                    # A response arriving after logout cannot restore privileged UI state.
                    def late_response(route):
                        response=route.fetch()
                        page.locator('#logout').click()
                        route.fulfill(response=response)
                    page.route('**/api/v1/admin/directory/check',late_response)
                    directory_password();page.locator('#directoryCheck').click()
                    expect(page.locator('#ownerPanel')).to_be_hidden()
                    expect(page.locator('#directoryStatus')).to_have_text('')
                    expect(page.locator('[name=directory_password]')).to_have_value('')
                    page.unroute('**/api/v1/admin/directory/check',late_response)
                    # Persist only public receipt/account continuity through a Core restart.
                    stop(admin);admin=start_admin()
                    with httpx.Client(base_url=base,trust_env=False,timeout=5) as probe:
                        ready(probe,'/api/v1/health/live',admin,200)
                    page.reload();login()
                    expect(page.locator('#directoryStatus')).to_contain_text('Encontrado na última verificação')
                    assert page.evaluate('localStorage.length')==0
                    assert page.evaluate('sessionStorage.length')==0 and page.context.cookies()==[]
                    assert not errors,errors
                    if output:
                        Path(output).mkdir(parents=True,exist_ok=True)
                        page.locator('#directoryPanel').screenshot(path=str(Path(output)/'directory-control.png'))
                finally:
                    browser.close()
            with closing(sqlite3.connect(store.dir/'directory-control.sqlite3')) as db:
                retained=str(db.execute('SELECT * FROM publication').fetchall())
                record=json.loads(db.execute('SELECT record FROM publication').fetchone()[0])
            assert record['payload']['version']==3
            assert password not in retained and owner_password not in retained and 'PRIVATE KEY' not in retained
            with registry.db() as db:
                assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
            report={'result':'passed','transport':'browser -> Control -> real TLS 1.3 Directory',
                'checks':['owner_login','explicit_identity_creation','wrong_password_rejected',
                    'password_input_cleared','signed_publication','same_identity_renewal',
                    'authenticated_verification','account_change_rejected','no_html_injection',
                    'late_response_after_logout_discarded','core_restart_receipt_persistence',
                    'no_browser_storage','no_saved_password_or_private_key_in_receipt','directory_sessions_logged_out','scoped_renewal_without_password'],
                'automatic_renewal':True,'android_directory':False,'media':False,'physical_nas':False}
            if output:
                (Path(output)/'directory-control.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
            print(json.dumps(report))
        finally:
            for process in reversed(processes):
                if process.poll() is None:stop(process)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output');parser.add_argument('--channel')
    args=parser.parse_args();run(args.output,args.channel)
