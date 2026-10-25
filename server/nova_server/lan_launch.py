"""Three independent HTTPS processes, each with its own key/state mount."""
import argparse
import os
from pathlib import Path
import ssl

from .lan import load,origin,validate_leaf


def application(role,config,identity,state):
    config=load(config);identity=Path(identity)
    database=Path(state)/('directory.sqlite3' if role=='directory' else 'nova.sqlite3')
    if not database.is_file():raise ValueError('Prepared deployment state missing; refuse a new identity')
    key=identity/'server.key'
    if key.is_symlink() or not key.is_file() or (os.name=='posix' and key.stat().st_mode & 0o077):
        raise ValueError('Private TLS key/permissions required')
    validate_leaf(identity/'server.crt',config['ip'])
    if role=='admin':
        from .app import make_app
        api=make_app(state,allowed_hosts=[config['ip']],directory_options={
            'origin':origin(config,'directory'),'ca':identity/'lan-ca.crt',
            'client_origin':origin(config,'client'),'certificate':identity/'client.crt'})
        @api.middleware('http')
        async def private_admin(request,call_next):
            from fastapi.responses import JSONResponse
            if request.url.scheme!='https':return JSONResponse({'error':'https_required'},status_code=400)
            return await call_next(request)
        api.state.admin_exposure='private_lan_https'
        import hashlib
        from cryptography.hazmat.primitives import serialization
        directory_leaf=validate_leaf(identity/'directory.crt',config['ip'])
        api.state.lan_configuration={'directory':origin(config,'directory'),'client':origin(config,'client'),
            'fingerprint':hashlib.sha256(directory_leaf.public_bytes(serialization.Encoding.DER)).hexdigest()}
        return api,config
    if role=='client':
        from .client_api import make_client_app
        return make_client_app(state,origin(config,'client'),require_directory=True),config
    if role=='directory':
        from nova_directory.api import make_directory
        bootstrap=identity/'nova-directory.json'
        return make_directory(state,origin(config,'directory'),operator_id=config['operator_id'],
                              bootstrap_profile=bootstrap),config
    raise ValueError('Unknown service role')


def main():
    import uvicorn
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role',choices=('admin','client','directory'))
    parser.add_argument('--config',default='/identity/deployment.json')
    parser.add_argument('--identity',default='/identity')
    parser.add_argument('--state',default='/data')
    args=parser.parse_args()
    os.environ['NOVA_STATE_DIR']=args.state
    api,config=application(args.role,args.config,args.identity,args.state)
    runtime=uvicorn.Config(api,host='0.0.0.0',port=config['ports'][args.role],
        ssl_certfile=str(Path(args.identity)/'server.crt'),ssl_keyfile=str(Path(args.identity)/'server.key'),
        proxy_headers=False,access_log=False)
    runtime.load();runtime.ssl.minimum_version=ssl.TLSVersion.TLSv1_3
    uvicorn.Server(runtime).run()


if __name__=='__main__':main()
