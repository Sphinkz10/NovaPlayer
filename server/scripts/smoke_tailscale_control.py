"""Actual owner browser approval/disable, disposable prepared identities only."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import httpx
from playwright.sync_api import sync_playwright,expect

SERVER=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SERVER))
from scripts.lan_install import prepare as prepare_lan
from scripts.tailscale_prepare import prepare
from scripts.smoke_devices_tls import free_port,ready,stop


def run(output=None,channel=None):
    with tempfile.TemporaryDirectory(prefix='nova-tailscale-control-') as temporary:
        root=Path(temporary);installation=root/'installation';patch=root/'patch'
        password='synthetic-owner-only-password'
        info=prepare_lan(installation,ip='192.168.50.20',state_root='/mnt/test/nova',media_a='/mnt/test/a',
            media_b='/mnt/test/b',uid=10001,gid=10001,image='ghcr.io/sphinkz10/nova-core@sha256:'+'a'*64,
            version='25.10.5',username='owner',password=password)
        profile=prepare(installation,patch,gateway='100.64.0.1',image='ghcr.io/sphinkz10/nova-core@sha256:'+'b'*64)
        state=installation/'copiar-para-nas'
        for file in (patch/'copiar-para-nas').rglob('*'):
            if file.is_file():shutil.copy2(file,state/file.relative_to(patch/'copiar-para-nas'))
        port=free_port();base=f'http://127.0.0.1:{port}'
        env={**os.environ,'NOVA_STATE_DIR':str(state/'nova'),'NOVA_JELLYFIN_URL':'http://127.0.0.1:1',
            'NOVA_TAILSCALE_MANAGED':'1','NOVA_TAILSCALE_PUBLIC_CONFIG':str(state/'identity/admin/tailscale-public.json'),
            'NOVA_TAILSCALE_BASE_ORIGIN':info['client'],'NOVA_TAILSCALE_CERTIFICATE_FILE':str(state/'identity/admin/client.crt')}
        process=subprocess.Popen([sys.executable,'-m','uvicorn','nova_server.app:app','--host','127.0.0.1',
            '--port',str(port),'--no-proxy-headers','--no-access-log'],cwd=SERVER,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            with httpx.Client(base_url=base,trust_env=False,timeout=5) as client:ready(client,'/api/v1/health/live',process,200)
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(headless=True,**({'channel':channel} if channel else {}))
                try:
                    page=browser.new_page(viewport={'width':1280,'height':1000});errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(base)
                    page.locator('#login [name=username]').fill('owner')
                    page.locator('#login [name=password]').fill(password)
                    page.locator('#login button').click()
                    expect(page.locator('#tailscaleStatus')).to_contain_text('Perfil preparado')
                    expect(page.locator('#tailscalePolicy')).to_contain_text(profile['certificate_sha256'])
                    expect(page.locator('#tailscalePolicy')).to_contain_text('https://100.64.0.1:8920')
                    expect(page.locator('#tailscaleApprove')).to_be_enabled()
                    expect(page.locator('#tailscaleDisable')).to_be_disabled()
                    if output:
                        output=Path(output);output.mkdir(parents=True,exist_ok=True)
                        page.locator('#tailscalePanel').screenshot(path=str(output/'tailscale-pending.png'))
                    page.locator('#tailscaleApprove').click()
                    expect(page.locator('#tailscaleStatus')).to_contain_text('Perfil aprovado')
                    expect(page.locator('#tailscaleDisable')).to_be_enabled()
                    expect(page.locator('#tailscaleApprove')).to_be_disabled()
                    if output:page.locator('#tailscalePanel').screenshot(path=str(output/'tailscale-approved.png'))
                    page.reload()
                    expect(page.locator('#ownerPanel')).to_be_hidden()
                    page.locator('#login [name=username]').fill('owner')
                    page.locator('#login [name=password]').fill(password)
                    page.locator('#login button').click()
                    expect(page.locator('#tailscaleStatus')).to_contain_text('Perfil aprovado')
                    page.locator('#tailscaleDisable').click()
                    expect(page.locator('#tailscaleStatus')).to_contain_text('Perfil preparado')
                    expect(page.locator('#tailscaleMessage')).to_contain_text('Perfil desativado')
                    # A response begun in a previous owner session cannot repopulate the panel.
                    def logout_during_refresh(route):
                        response=route.fetch()
                        page.evaluate("document.querySelector('#logout').click()")
                        route.fulfill(response=response)
                    page.route('**/api/v1/admin/connect/tailscale',logout_during_refresh)
                    page.locator('#tailscaleRefresh').click()
                    expect(page.locator('#ownerPanel')).to_be_hidden()
                    expect(page.locator('#tailscalePolicy')).to_be_empty()
                    expect(page.locator('#tailscaleApprove')).to_be_disabled()
                    assert page.evaluate('localStorage.length')==0 and not browser.contexts[0].cookies() and not errors
                finally:browser.close()
            report={'result':'passed','checks':['offline_ca_and_client_key_preserved','prepared_profile_visible',
                'owner_compares_certificate_and_origin','approval_buttons_follow_state','owner_approves_profile',
                'approval_survives_page_reload','owner_disables_profile','logout_discards_late_response',
                'no_browser_storage_or_script_errors'], 'gateway_enrolled':False,'physical_nas':False,
                'certificate_sha256':profile['certificate_sha256']}
            if output:(output/'tailscale-control.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
            print(json.dumps(report))
        finally:stop(process)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output');parser.add_argument('--channel')
    args=parser.parse_args();run(args.output,args.channel)
