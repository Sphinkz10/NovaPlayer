"""Bounded, non-privileged availability probe; readiness is not library access."""
from __future__ import annotations
import asyncio
import json
import httpx

MAX_INFO_BYTES = 16 * 1024
PROBE_TIMEOUT = 4.0


async def probe_jellyfin(url: str, transport=None, *, expected_server_id: str | None = None) -> dict:
    endpoint = url.rstrip('/') + '/System/Info/Public'
    try:
        # A total deadline also limits a server that trickles bytes forever.
        async with asyncio.timeout(PROBE_TIMEOUT):
            async with httpx.AsyncClient(timeout=PROBE_TIMEOUT, follow_redirects=False,
                                         transport=transport, trust_env=False) as client:
                async with client.stream('GET', endpoint, headers={'Accept-Encoding':'identity'}) as response:
                    status = response.status_code
                    if status in (401, 403):
                        return {'state': 'unauthorized', 'reason': 'O serviço recusou o pedido.'}
                    if status in (408, 425, 429, 500, 502, 503, 504):
                        return {'state': 'unavailable', 'reason': 'Jellyfin temporariamente indisponível.'}
                    if status != 200:
                        return {'state': 'unexpected', 'reason': 'Resposta HTTP inesperada.', 'status_code': status}
                    if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                        return {'state': 'invalid_response', 'reason': 'Compressão não permitida neste diagnóstico.'}
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        if len(body) + len(chunk) > MAX_INFO_BYTES:
                            return {'state': 'invalid_response', 'reason': 'Resposta Jellyfin demasiado grande.'}
                        body.extend(chunk)
    except (httpx.TimeoutException, TimeoutError):
        return {'state': 'timeout', 'reason': 'Jellyfin não respondeu dentro do prazo.'}
    except httpx.HTTPError:
        return {'state': 'offline', 'reason': 'Serviço Jellyfin inacessível.'}
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        return {'state': 'invalid_response', 'reason': 'JSON inválido do Jellyfin.'}
    if (not isinstance(payload, dict) or payload.get('ProductName') != 'Jellyfin'
            or not isinstance(payload.get('Id'), str) or not payload['Id'].strip()
            or len(payload['Id']) > 256 or type(payload.get('StartupWizardCompleted')) is not bool):
        return {'state': 'invalid_response', 'reason': 'Identidade, produto ou estado Jellyfin inválido.'}
    if expected_server_id is not None and payload['Id'] != expected_server_id:
        return {'state': 'identity_mismatch', 'reason': 'A identidade Jellyfin difere da configurada.'}
    identity = {'server_id': payload['Id'], 'identity_verified': expected_server_id is not None}
    if payload['StartupWizardCompleted'] is False:
        return {'state': 'setup_required', **identity, 'reason': 'Assistente Jellyfin pendente.'}
    version = payload.get('Version')
    return {'state': 'ready', **identity,
            'version': version if isinstance(version, str) and len(version) <= 100 else 'desconhecida'}
