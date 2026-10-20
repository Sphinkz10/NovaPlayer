import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from scripts.lan_install import prepare
from nova_server.lan import validate,lan_ip
from nova_server.lan_launch import application
from nova_server.security import verify_password
from nova_server.storage import Store
from nova_directory.store import Registry,DirectoryError


PASSWORD='lan-fixture-password-only'


@pytest.fixture
def deployment(tmp_path):
    folder=tmp_path/'new'
    info=prepare(folder,ip='192.168.50.20',state_root='/mnt/pool/nova',media_a='/mnt/pool/a',media_b='/mnt/pool/b',
                 uid=10001,gid=10001,image='ghcr.io/sphinkz10/nova-core@sha256:'+'a'*64,version='25.10.5',username='owner',password=PASSWORD)
    return folder,info


def test_new_bundle_separates_keys_state_and_endpoints(deployment):
    folder,info=deployment
    config=json.loads((folder/'instalar-no-truenas.yaml').read_text())
    assert set(config['services'])=={'jellyfin','nova-admin','nova-client','nova-directory'}
    assert 'ports' not in config['services']['jellyfin']
    for role in ('admin','client','directory'):
        service=config['services']['nova-'+role]
        port=info[{'admin':'control','client':'client','directory':'tv_directory'}[role]].split(':')[-1]
        assert service['ports']==[f'192.168.50.20:{port}:{port}/tcp']
        assert service['read_only'] and service['cap_drop']==['ALL'] and service['user']=='10001:10001'
        assert service['volumes'][1]['read_only'] and service['volumes'][1]['source'].endswith('/identity/'+role)
        assert all(not m['bind']['create_host_path'] for m in service['volumes'])
        assert not any('docker.sock' in str(m) or 'ca.key' in str(m) for m in service['volumes'])
    assert all(v['read_only'] for v in config['services']['jellyfin']['volumes'][-2:])
    assert not list((folder/'copiar-para-nas').rglob('*ca.key'))
    assert len({(folder/'copiar-para-nas/identity'/role/'server.key').read_bytes() for role in ('admin','client','directory')})==3
    for path in folder.rglob('*'):
        if path.is_file():assert PASSWORD.encode() not in path.read_bytes()
    admin=Store(folder/'copiar-para-nas/nova').get_admin('owner')
    assert verify_password(admin[1],PASSWORD)


@pytest.mark.parametrize('ip',['0.0.0.0','127.0.0.1','8.8.8.8','100.64.1.2','192.168.1.1:9443','192.168.001.1','localhost'])
def test_lan_requires_exact_private_ip(ip):
    with pytest.raises(ValueError):lan_ip(ip)


def test_no_existing_installation_is_overwritten(deployment):
    folder,_=deployment
    before=(folder/'copiar-para-nas/nova/nova.sqlite3').read_bytes()
    with pytest.raises(FileExistsError):prepare(folder,ip='192.168.50.20',state_root='/mnt/pool/nova',media_a='/mnt/pool/a',media_b='/mnt/pool/b',
        uid=10001,gid=10001,image='ghcr.io/sphinkz10/nova-core@sha256:'+'a'*64,version='25.10.5',username='owner',password=PASSWORD)
    assert (folder/'copiar-para-nas/nova/nova.sqlite3').read_bytes()==before


def test_lan_refuses_anonymous_pairing_before_admin_or_publication(deployment):
    folder,info=deployment;nas=folder/'copiar-para-nas';identity=nas/'identity/client'
    assert not (nas/'nova/directory-control.sqlite3').exists()
    api,_=application('client',identity/'deployment.json',identity,nas/'nova')
    with TestClient(api,base_url=info['client']) as client:
        response=client.post('/api/v1/device/authorize',json={'label':'Unbound TV'})
        assert response.status_code==403 and response.json()['error']=='directory_identity_required'


def test_public_bootstrap_matches_pinned_leaf_and_public_directory_only(deployment):
    folder,info=deployment;nas=folder/'copiar-para-nas';identity=nas/'identity/directory'
    api,_=application('directory',identity/'deployment.json',identity,nas/'directory')
    with TestClient(api,base_url=info['tv_directory']) as client:
        result=client.get('/api/v1/directory/bootstrap');assert result.status_code==200
        profile=result.json();cert=x509.load_pem_x509_certificate(profile['certificate_pem'].encode())
        assert hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()==info['tv_fingerprint']
        assert PASSWORD not in result.text and 'PRIVATE KEY' not in result.text
        for path in ('/api/v1/admin/overview','/api/v1/media/libraries/a/items','/static/control.js'):
            assert client.get(path).status_code==404
        assert client.post('/api/v1/directory/operator/accounts',json={'username':'alice','password':PASSWORD,'entry_id':str(uuid.uuid4())}).status_code==401
        login=client.post('/api/v1/directory/login',json={'username':'owner','password':PASSWORD}).json()
        headers={'Authorization':'Bearer '+login['access_token']}
        assert client.post('/api/v1/directory/operator/accounts',headers=headers,json={
            'username':'alice','password':PASSWORD,'entry_id':str(uuid.uuid4())}).status_code==404
    registry=Registry(nas/'directory',info['tv_directory'])
    with registry.db() as db:assert db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]==1


def test_admin_requires_https_and_owner_and_client_never_mounts_admin(deployment,monkeypatch):
    folder,info=deployment;nas=folder/'copiar-para-nas';identity=nas/'identity/admin'
    monkeypatch.setenv('NOVA_STATE_DIR',str(nas/'nova'))
    api,_=application('admin',identity/'deployment.json',identity,nas/'nova')
    with TestClient(api,base_url=info['control']) as client:
        assert client.get('/api/v1/admin/lan').status_code==401
        token=client.post('/api/v1/admin/login',json={'username':'owner','password':PASSWORD}).json()['access_token']
        settings=client.get('/api/v1/admin/lan',headers={'Authorization':'Bearer '+token}).json()
        assert settings['fingerprint']==info['tv_fingerprint']
        assert client.post('/api/v1/admin/directory/accounts',headers={'Authorization':'Bearer '+token},json={
            'username':'owner','password':PASSWORD,'member_username':'alice','member_password':PASSWORD}).status_code==409
    with TestClient(api,base_url=info['control'].replace('https:','http:')) as client:assert client.get('/').status_code==400
    identity=nas/'identity/client';api,_=application('client',identity/'deployment.json',identity,nas/'nova')
    with TestClient(api,base_url=info['client']) as client:
        for path in ('/','/api/v1/admin/overview','/api/v1/directory/bootstrap'):
            assert client.get(path).status_code==404
