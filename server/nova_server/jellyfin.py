"""Read-only non-privileged Jellyfin availability probe."""
from __future__ import annotations
import httpx

async def probe_jellyfin(url: str, transport=None) -> dict:
    endpoint=url.rstrip('/')+'/System/Info/Public'
    try:
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=False,transport=transport) as client:
            r=await client.get(endpoint)
    except httpx.TimeoutException:
        return {'state':'timeout','reason':'Jellyfin não respondeu dentro do prazo.'}
    except httpx.HTTPError:
        return {'state':'offline','reason':'Serviço Jellyfin inacessível.'}
    if r.status_code in (401,403):
        return {'state':'unauthorized','reason':'O serviço recusou o pedido.'}
    if r.status_code in (429,500,502,503,504):
        return {'state':'unavailable','reason':'Jellyfin temporariamente indisponível.'}
    if r.status_code != 200:
        return {'state':'unexpected','reason':'Resposta HTTP inesperada.','status_code':r.status_code}
    try:
        payload=r.json()
    except ValueError:
        return {'state':'invalid_response','reason':'JSON inválido do Jellyfin.'}
    if not isinstance(payload,dict) or not isinstance(payload.get('Id'),str) or not payload['Id']:
        return {'state':'invalid_response','reason':'Identidade do Jellyfin em falta.'}
    if payload.get('StartupWizardCompleted') is False:
        return {'state':'setup_required','server_id':payload['Id'],'reason':'Assistente Jellyfin pendente.'}
    return {'state':'ready','server_id':payload['Id'],'version':str(payload.get('Version','desconhecida'))}
