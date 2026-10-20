"""Actual Media3 video decode on disposable API 26/35 emulators, through pinned NOVA TLS."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'server'),str(ROOT/'server/scripts'),str(ROOT/'server/tests')]
from m3_lab import M3Lab
from jellyfin_m3_fixture import jellyfin_http
from smoke_pairing_android import adb,provision_file,PACKAGE
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from nova_server.devices import Devices


def run():
    if os.environ.get('GITHUB_ACTIONS')!='true' or adb('shell','getprop','ro.kernel.qemu').strip()!='1':
        raise SystemExit('Only the disposable GitHub Actions emulator is permitted.')
    out=ROOT/'connect/test-results/m4';out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nova-m4-emulator-') as folder,jellyfin_http() as (jf,url):
        movie=Path(folder)/'synthetic.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=320x180:rate=24',
                        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','40','-c:v','libx264','-preset','ultrafast',
                        '-g','24','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(movie)],check=True,timeout=60)
        jf.media_content=movie.read_bytes()
        libraries=[{'id':'a'*32,'name':'Biblioteca A'},{'id':'b'*32,'name':'Biblioteca B'}]
        for i,library in enumerate(libraries):
            identity=str(i+1)*32
            jf.media_items[library['id']]=[{'Id':identity,'Name':'Filme '+('A' if i==0 else 'B'),'Type':'Movie',
                'RunTimeTicks':400000000,'Overview':'Vídeo sintético de teste.','MediaSources':[
                    {'Id':identity,'Protocol':'File','Path':'/fixture/movie.mp4'}],'UserData':{'PlaybackPositionTicks':0}}]
        with M3Lab(folder,url,libraries=libraries,jellyfin_id=jf.sid) as lab:
            tokens,_=lab.pair('alice',0)
            fixture={'origin':lab.origin,'server_id':Devices(lab.store).identity(),'account':lab.accounts['alice'],
                     'certificate':base64.b64encode(x509.load_pem_x509_certificate(lab.cert.read_bytes()).public_bytes(serialization.Encoding.DER)).decode(),
                     'tokens':tokens,'library':libraries[0]['id'],'item':'1'*32,'other_library':libraries[1]['id']}
            # Credentials exist only in the private files of the instrumentation target.
            adb('reverse',f'tcp:{lab.api_port}',f'tcp:{lab.api_port}')
            try:
                provision_file('mfour-fixture.json',json.dumps(fixture).encode())
                adb('shell','am','force-stop',PACKAGE)
                output=adb('shell','am','instrument','-w','-r','-e','phase','m4-cinema',
                           PACKAGE+'.test/com.novacinema.connect.DevicePairingInstrumentation',timeout=180)
                (out/'cinema.txt').write_text(output,encoding='utf8')
                assert 'INSTRUMENTATION_RESULT: nova_pairing=passed' in output,output
                assert 'INSTRUMENTATION_CODE: -1' in output,output
                assert any(event['path'].endswith('/Stopped') and event['PositionTicks']>=100000000 for event in jf.media_events)
                assert any(position>0 for position in jf.media_ranges)
                report={'result':'passed','api':int(adb('shell','getprop','ro.build.version.sdk').strip()),
                        'checks':['catalog_dpad','detail_dpad','first_video_frame','seek','pause','progress_stop',
                                  'resume_after_reopen','cross_library_denied'],
                        'apk_sha256':hashlib.sha256((ROOT/'connect/app/build/outputs/apk/debug/app-debug.apk').read_bytes()).hexdigest(),
                        'synthetic_video_sha256':hashlib.sha256(jf.media_content).hexdigest(),
                        'jellyfin':'isolated HTTP fixture; actual Jellyfin is a separate Docker test',
                        'physical_tv':False,'method':'static original bytes; Media3 progressive decode'}
                (out/'m4.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps(report))
            finally:
                adb('shell','am','force-stop',PACKAGE)
                adb('shell','run-as',PACKAGE,'rm','-f','files/mfour-fixture.json')
                adb('reverse','--remove',f'tcp:{lab.api_port}')


if __name__=='__main__':run()
