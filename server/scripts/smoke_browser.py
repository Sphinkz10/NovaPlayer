"""Real browser regression: login, diagnostics, three provider drafts and logout.

Run from server/: python scripts/smoke_browser.py [--channel msedge] [--output DIR]
Uses only disposable local state and synthetic settings; never contacts providers.
"""
import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

# Explicit fixture setup; the browser still performs the authenticated owner decisions.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nova_server.devices import Devices, DeviceError
from nova_server.storage import Store
from playwright.sync_api import sync_playwright, expect


def run(channel=None, output=None):
    with tempfile.TemporaryDirectory(prefix='nova-browser-') as folder:
        with socket.socket() as port_picker:
            port_picker.bind(('127.0.0.1', 0))
            port = port_picker.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        secret = secrets.token_urlsafe(48)
        Path(folder, 'bootstrap.token').write_text(secret, encoding='ascii')
        env = {**os.environ, 'NOVA_STATE_DIR':folder, 'NOVA_JELLYFIN_URL':'http://127.0.0.1:1'}
        server = subprocess.Popen([
            sys.executable, '-m', 'uvicorn', 'nova_server.app:app', '--host', '127.0.0.1',
            '--port', str(port), '--no-proxy-headers', '--no-access-log'],
            cwd=Path(__file__).resolve().parents[1], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with httpx.Client(base_url=base, trust_env=False, timeout=5) as client:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError('Temporary API exited before startup')
                    try:
                        if client.get('/api/v1/health/live').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError('Temporary API did not start')
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, **({'channel':channel} if channel else {}))
                try:
                    page = browser.new_page(viewport={'width':1280,'height':1000})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base)
                    expect(page.locator('#bootstrapPanel')).to_be_visible()
                    page.locator('[name=bootstrap_code]').fill('invalid-code')
                    page.locator('[name=owner_name]').fill('owner')
                    page.locator('[name=owner_password]').fill('browser-only-test-passphrase')
                    page.locator('#bootstrap button').click()
                    expect(page.locator('#bootstrapMessage')).to_contain_text('Não foi possível criar')
                    page.locator('[name=bootstrap_code]').fill(secret)
                    page.locator('#bootstrap button').click()
                    expect(page.locator('#bootstrapPanel')).to_be_hidden()
                    expect(page.locator('[name=bootstrap_code]')).to_have_value('')
                    page.locator('#login [name=username]').fill('owner')
                    page.locator('#login [name=password]').fill('wrong')
                    page.locator('#login button').click()
                    expect(page.locator('#loginError')).to_have_text('Login inválido.')
                    page.locator('#login [name=password]').fill('browser-only-test-passphrase')
                    page.locator('#login button').click()
                    expect(page.locator('#ownerPanel')).to_be_visible()
                    expect(page.locator('#overview')).to_contain_text('offline')
                    expect(page.locator('#overview')).to_contain_text('por verificar')
                    if output:
                        # Export an inert, offline copy of this real test UI, without
                        # scripts, session token, form values or network operations.
                        output.mkdir(parents=True,exist_ok=True)
                        page.wait_for_function("document.querySelector('#directoryStatus').textContent !== 'A consultar configuração…'")
                        shell=page.locator('#ownerPanel').evaluate('''node=>{
                            const copy=node.cloneNode(true);
                            copy.querySelectorAll('input,select,button').forEach(item=>{item.disabled=true;});
                            copy.querySelectorAll('input').forEach(item=>item.removeAttribute('value'));
                            return copy.outerHTML;
                        }''')
                        css=(Path(__file__).resolve().parents[1]/'nova_server/static/control.css').read_text(encoding='utf-8-sig')
                        navigation='''const pages=new Set(['overview','libraries','people','directory','connections']);
                        function show(key){if(!pages.has(key))key='overview';
                          document.querySelectorAll('.control-view').forEach(v=>v.hidden=v.id!=='view-'+key);
                          document.querySelectorAll('.sidebar nav [data-page]').forEach(a=>{
                            if(a.dataset.page===key)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});}
                        document.querySelectorAll('[data-page]').forEach(a=>a.addEventListener('click',e=>{
                          e.preventDefault();location.hash=a.dataset.page;show(a.dataset.page);
                          document.getElementById('heading-'+a.dataset.page).focus();window.scrollTo(0,0);}));
                        window.addEventListener('hashchange',()=>show(location.hash.slice(1)));show('overview');'''
                        preview='<!doctype html><html lang="pt-PT"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NOVA Control · pré-visualização</title>'
                        preview+='<style>'+css+' .preview-label{padding:12px 24px;background:#2b2539;color:#e0d3ff;font-size:13px;line-height:1.6}</style>'
                        preview+='<div class="preview-label">Pré-visualização do Control · dados de teste · sem ligação ao NAS. Os menus funcionam; as operações estão desativadas.</div>'
                        preview+=shell+'<script>'+navigation+'</script></html>'
                        (output/'PRE_VISUALIZACAO_CONTROL.html').write_text(preview,encoding='utf8')
                        page.mouse.move(0,0)
                        page.screenshot(path=str(output/'control-inicio.png'),full_page=True)
                    expect(page.locator('#login [name=password]')).to_have_value('')
                    expect(page.locator('#publicPanel')).to_be_hidden()
                    assert page.locator('.control-view:visible').count()==1
                    page.locator('.sidebar nav [data-page=libraries]').focus()
                    page.keyboard.press('Enter')
                    expect(page.locator('#heading-libraries')).to_be_focused()
                    page.go_back()
                    expect(page.locator('#view-overview')).to_be_visible()
                    page.go_forward()
                    expect(page.locator('#view-libraries')).to_be_visible()
                    expect(page.locator('.sidebar nav [data-page=libraries]')).to_have_attribute('aria-current','page')
                    page.locator('.sidebar nav [data-page=connections]').click()
                    expect(page.locator('#connectMessage')).to_contain_text('Acesso remoto desativado')
                    page.locator('.sidebar nav [data-page=libraries]').click()
                    page.locator('[name=jf_username]').fill('owner')
                    page.locator('[name=jf_password]').fill('synthetic-jellyfin-password')
                    page.locator('#jellyfinSetup button[type=submit]').click()
                    expect(page.locator('#setupMessage')).to_contain_text('Não foi possível concluir')
                    expect(page.locator('[name=jf_password]')).to_have_value('')
                    configurations = {
                        'wireguard':{'endpoint_host':'vpn.example.org','endpoint_port':'51820'},
                        'tailscale':{'tailnet':'test.example'},
                        'netbird':{'management_url':'https://api.netbird.io'},
                    }
                    page.locator('.sidebar nav [data-page=connections]').click()
                    for provider, fields in configurations.items():
                        page.locator('#provider').select_option(provider)
                        page.locator('[name=gateway_url]').fill('https://10.90.0.1:8920')
                        for name, value in fields.items():
                            page.locator(f'[name={name}]').fill(value)
                        with page.expect_response(lambda r: '/connect/draft' in r.url) as result:
                            page.locator('#connectDraft button').click()
                        assert result.value.status == 200
                        expect(page.locator('#connectMessage')).to_contain_text('Rascunho guardado')
                    device_service = Devices(Store(folder))
                    device_label = '<img src=x onerror=alert(1)> TV'
                    grant = device_service.start(device_label)
                    page.locator('.sidebar nav [data-page=people]').click()
                    def stale_review(route):
                        response = route.fetch()
                        page.evaluate("const input=document.querySelector('[name=user_code]'); input.value='INVALIDX'; input.dispatchEvent(new Event('input', {bubbles:true}));")
                        route.fulfill(response=response)
                    page.route('**/api/v1/admin/devices/inspect', stale_review)
                    page.locator('[name=user_code]').fill(grant['user_code'])
                    with page.expect_response(lambda r: '/devices/inspect' in r.url):
                        page.locator('#deviceLookup button').click()
                    expect(page.locator('#deviceLookup button')).to_be_enabled()
                    expect(page.locator('#deviceReview')).to_be_hidden()
                    page.unroute('**/api/v1/admin/devices/inspect', stale_review)
                    page.locator('[name=user_code]').fill(grant['user_code'])
                    page.locator('#deviceLookup button').click()
                    expect(page.locator('#deviceReview')).to_be_visible()
                    expect(page.locator('#deviceDescription')).to_contain_text(device_label)
                    assert page.locator('#deviceReview img').count() == 0
                    # Changing the code invalidates the review instead of approving stale data.
                    page.locator('[name=user_code]').fill('INVALIDX')
                    expect(page.locator('#deviceReview')).to_be_hidden()
                    page.locator('[name=user_code]').fill(grant['user_code'])
                    page.locator('#deviceLookup button').click()
                    expect(page.locator('#deviceReview')).to_be_visible()
                    page.locator('#deviceApprove').click()
                    expect(page.locator('#deviceMessage')).to_contain_text('Aprovado')
                    device_tokens = device_service.poll(grant['device_code'])
                    page.locator('#deviceRefresh').click()
                    expect(page.locator('#deviceList')).to_contain_text(device_label)
                    page.locator('#deviceList button').click()
                    expect(page.locator('#deviceList')).to_contain_text('Revogado')
                    try:
                        device_service.authenticate(device_tokens['access_token'])
                    except DeviceError:
                        pass
                    else:
                        raise AssertionError('Browser revocation did not invalidate the token')
                    # Refresh re-reads persisted drafts through the authenticated API.
                    page.locator('.sidebar nav [data-page=overview]').click()
                    page.locator('#refresh').click()
                    page.locator('.sidebar nav [data-page=connections]').click()
                    expect(page.locator('#connectMessage')).to_contain_text('Acesso remoto desativado')
                    page.locator('#provider').select_option('tailscale')
                    expect(page.locator('[name=tailnet]')).to_have_value('test.example')
                    assert page.evaluate('localStorage.length') == 0
                    assert not browser.contexts[0].cookies()
                    if output:
                        output.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(output/'control.png'), full_page=True)
                    # Each real screen fits desktop, phone and narrow mobile widths.
                    for width in (1280,390,320):
                        page.set_viewport_size({'width':width,'height':900})
                        for view in ('overview','libraries','people','directory','connections'):
                            page.locator(f'.sidebar nav [data-page={view}]').click()
                            assert page.locator('.control-view:visible').count()==1
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width,view)
                            if output and width in (1280,390):
                                page.screenshot(path=str(output/f'control-{view}-{width}.png'),full_page=True)
                    page.locator('#logout').click()
                    expect(page.locator('#ownerPanel')).to_be_hidden()
                    expect(page.locator('#publicPanel')).to_be_visible()
                    if output:page.screenshot(path=str(output/'control-login-320.png'),full_page=True)
                    page.reload()
                    expect(page.locator('#ownerPanel')).to_be_hidden()
                    assert not errors, errors
                    report = {'result':'passed', 'browser':channel or 'chromium',
                              'checks':['bootstrap_invalid_code','bootstrap_in_browser','invalid_login','login_panel','form_reset','unverified_media','setup_offline_password_cleared',
                                        'three_provider_drafts','device_review_approval_revocation','device_label_xss_blocked','stale_device_review_discarded','reload_persistence','no_local_storage',
                                        'no_cookies','logout','no_page_errors','single_visible_screen','browser_back_forward',
                                        'navigation_focus_and_current_page','responsive_1280_390_320','login_restored_after_logout']}
                    if output:
                        (output/'browser.json').write_text(json.dumps(report, indent=2), encoding='utf8')
                    print(json.dumps(report))
                finally:
                    browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    run(args.channel, args.output)
