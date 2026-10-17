#!/usr/bin/env python3
"""Owner bootstrap from the server terminal; secret never printed."""
from __future__ import annotations
import getpass
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:8787/api/v1/admin/bootstrap'

def main():
    token_path=ROOT/'state/nova/bootstrap.token'
    if not token_path.is_file():
        print('Não há token de instalação. Talvez o admin já tenha sido configurado.')
        raise SystemExit(1)
    username=input('Utilizador admin (mín. 3 caracteres): ').strip()
    password=getpass.getpass('Palavra-passe admin (mín. 14 caracteres): ')
    confirm=getpass.getpass('Confirmar palavra-passe: ')
    if password != confirm:
        print('Palavras-passe diferentes.');raise SystemExit(2)
    payload=json.dumps({'username':username,'password':password}).encode()
    req=urllib.request.Request(URL,payload,headers={
        'Content-Type':'application/json',
        'X-NOVA-Bootstrap':token_path.read_text().strip()},method='POST')
    try:
        with urllib.request.urlopen(req,timeout=8) as r:
            result=json.load(r)
            print('Proprietário configurado:',result['admin'])
            print('Token inicial invalidado. Login local no painel: http://127.0.0.1:8787')
    except urllib.error.HTTPError as e:
        print('Erro ao configurar proprietário:',e.code)
        raise SystemExit(1)
    except urllib.error.URLError:
        print('NOVA Core indisponível. Inicia primeiro docker compose up -d --build')
        raise SystemExit(1)

if __name__=='__main__':main()
