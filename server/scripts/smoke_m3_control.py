"""Owner browser grants/revokes a verified family account; isolated Jellyfin fixture."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

SERVER=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(SERVER),str(SERVER/'tests')]
from m3_lab import M3Lab
from jellyfin_m3_fixture import jellyfin_http
from playwright.sync_api import sync_playwright,expect


def run(output=None,channel=None):
    with tempfile.TemporaryDirectory(prefix='nova-m3-control-') as folder,jellyfin_http() as (jf,url):
        libs=[{'id':'a'*32,'name':'Biblioteca A'},{'id':'b'*32,'name':'Biblioteca B'}]
        with M3Lab(folder,url,libraries=libs,jellyfin_id=jf.sid) as lab:
            directory=lab.directory_client('alice')
            try:assertion=directory.request('POST','assertions',{'entry_id':lab.entry})
            finally:directory.close()
            result=lab.tv.post('/api/v1/device/authorize',json={'label':'TV Alice','assertion':assertion})
            assert result.status_code==201;grant=result.json()
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,**({'channel':channel} if channel else {}))
                try:
                    page=browser.new_page(viewport={'width':1280,'height':1100});errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(lab.admin_origin)
                    page.locator('#login [name=username]').fill(lab.owner['username'])
                    page.locator('#login [name=password]').fill(lab.owner['password'])
                    page.locator('#login button').click();expect(page.locator('#ownerPanel')).to_be_visible()
                    def inspect():
                        page.locator('[name=user_code]').fill(grant['user_code'])
                        page.locator('#deviceLookup button').click()
                        expect(page.locator('#deviceReview')).to_be_visible()
                    inspect();expect(page.locator('#deviceDescription')).to_contain_text('Conta Directory verificada: alice')
                    expect(page.locator('#deviceApprove')).to_be_disabled()
                    expect(page.locator('[name=member_subject]')).to_have_value(lab.accounts['alice'])
                    page.locator('[name=member_libraries][value="'+libs[0]['id']+'"]').check()
                    page.locator('[name=member_admin]').fill(lab.jellyfin_credentials['username'])
                    page.locator('#memberForm [name=member_password]').fill(lab.jellyfin_credentials['password'])
                    page.locator('#memberForm button').click()
                    expect(page.locator('#memberForm [name=member_password]')).to_have_value('')
                    expect(page.locator('#memberMessage')).to_contain_text('Permissões verificadas')
                    expect(page.locator('#deviceReview')).to_be_hidden()
                    inspect();expect(page.locator('#deviceApprove')).to_be_enabled()
                    page.locator('#deviceApprove').click()
                    expect(page.locator('#deviceMessage')).to_contain_text('Aprovado')
                    response=lab.tv.post('/api/v1/device/token',json={'device_code':grant['device_code']})
                    assert response.status_code==200;tokens=response.json()
                    auth={'Authorization':'Bearer '+tokens['access_token']}
                    allowed=lab.tv.get('/api/v1/device/libraries',headers=auth)
                    assert allowed.status_code==200 and allowed.json()['libraries']==[libs[0]]
                    page.locator('#memberList button').click()
                    expect(page.locator('#memberMessage')).to_contain_text('Conta revogada')
                    assert lab.tv.get('/api/v1/device/libraries',headers=auth).status_code==401
                    assert page.evaluate('localStorage.length')==0 and page.evaluate('sessionStorage.length')==0
                    assert not page.context.cookies() and not errors
                    if output:
                        Path(output).mkdir(parents=True,exist_ok=True)
                        page.locator('#memberList').screenshot(path=str(Path(output)/'members.png'))
                finally:browser.close()
            report={'result':'passed','checks':['signed_account_review','approval_blocked_until_grant',
                'owner_selects_library','admin_password_cleared','fresh_review_after_grant',
                'owner_approves_tv','only_assigned_library','owner_revokes_account_and_device',
                'no_browser_storage_or_errors'],'jellyfin':'HTTP fixture','physical_nas':False}
            if output:(Path(output)/'m3-control.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
            print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output');parser.add_argument('--channel')
    args=parser.parse_args();run(args.output,args.channel)
