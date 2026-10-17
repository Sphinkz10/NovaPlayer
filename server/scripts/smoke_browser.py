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
                assert client.post('/api/v1/admin/bootstrap', json={
                    'username':'owner', 'password':'browser-only-test-passphrase'},
                    headers={'X-NOVA-Bootstrap':secret}).status_code == 201
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, **({'channel':channel} if channel else {}))
                try:
                    page = browser.new_page(viewport={'width':1280,'height':1000})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base)
                    page.locator('[name=username]').fill('owner')
                    page.locator('[name=password]').fill('wrong')
                    page.locator('#login button').click()
                    expect(page.locator('#loginError')).to_have_text('Login inválido.')
                    page.locator('[name=password]').fill('browser-only-test-passphrase')
                    page.locator('#login button').click()
                    expect(page.locator('#ownerPanel')).to_be_visible()
                    expect(page.locator('#overview')).to_contain_text('offline')
                    expect(page.locator('#overview')).to_contain_text('por verificar')
                    expect(page.locator('[name=password]')).to_have_value('')
                    expect(page.locator('#connectMessage')).to_contain_text('Acesso remoto desativado')
                    configurations = {
                        'wireguard':{'endpoint_host':'vpn.example.org','endpoint_port':'51820'},
                        'tailscale':{'tailnet':'test.example'},
                        'netbird':{'management_url':'https://api.netbird.io'},
                    }
                    for provider, fields in configurations.items():
                        page.locator('#provider').select_option(provider)
                        page.locator('[name=gateway_url]').fill('https://10.90.0.1:8920')
                        for name, value in fields.items():
                            page.locator(f'[name={name}]').fill(value)
                        with page.expect_response(lambda r: '/connect/draft' in r.url) as result:
                            page.locator('#connectDraft button').click()
                        assert result.value.status == 200
                        expect(page.locator('#connectMessage')).to_contain_text('Rascunho guardado')
                    # Refresh re-reads persisted drafts through the authenticated API.
                    page.locator('#refresh').click()
                    expect(page.locator('#connectMessage')).to_contain_text('Acesso remoto desativado')
                    page.locator('#provider').select_option('tailscale')
                    expect(page.locator('[name=tailnet]')).to_have_value('test.example')
                    assert page.evaluate('localStorage.length') == 0
                    assert not browser.contexts[0].cookies()
                    if output:
                        output.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(output/'control.png'), full_page=True)
                    page.locator('#logout').click()
                    expect(page.locator('#ownerPanel')).to_be_hidden()
                    page.reload()
                    expect(page.locator('#ownerPanel')).to_be_hidden()
                    assert not errors, errors
                    report = {'result':'passed', 'browser':channel or 'chromium',
                              'checks':['invalid_login','login_panel','form_reset','unverified_media',
                                        'three_provider_drafts','reload_persistence','no_local_storage',
                                        'no_cookies','logout','no_page_errors']}
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
