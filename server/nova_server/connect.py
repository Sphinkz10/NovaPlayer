"""Versioned provider configuration drafts. No provider credentials or networking yet.

Saving a draft never enrolls a peer, changes routes, starts a daemon or enables
remote access. Runtime adapters must implement the contract before activation.
"""
from enum import Enum
from ipaddress import IPv4Address, IPv4Network
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderId(str, Enum):
    WIREGUARD = 'wireguard'
    TAILSCALE = 'tailscale'
    NETBIRD = 'netbird'


PRIVATE_NETWORKS = tuple(IPv4Network(value) for value in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10'))


def https_origin(value: str, private: bool = False) -> str:
    """Only an unambiguous HTTPS origin; this validator performs no DNS/network I/O."""
    if value != value.strip() or any(ord(c) < 33 or c in '\\%?#' for c in value):
        raise ValueError('Indica uma origem HTTPS sem credenciais, caminho, query ou fragmento.')
    url = urlsplit(value)
    if (url.scheme != 'https' or not url.hostname or url.username is not None
            or url.password is not None or url.path not in ('', '/')
            or (url.port is not None and not 1 <= url.port <= 65535)):
        raise ValueError('Origem HTTPS inválida.')
    if private:
        address = IPv4Address(url.hostname)
        if not any(address in network for network in PRIVATE_NETWORKS):
            raise ValueError('O gateway deve usar um IPv4 privado dedicado ao serviço NOVA.')
    return value.rstrip('/')


class ProviderDraft(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal[1] = 1
    gateway_url: str = Field(min_length=9, max_length=512)

    @field_validator('gateway_url')
    @classmethod
    def private_gateway(cls, value: str) -> str:
        return https_origin(value, private=True)


class WireGuardDraft(ProviderDraft):
    provider: Literal['wireguard']
    gateway_mode: Literal['managed', 'existing']
    endpoint_host: str = Field(min_length=1, max_length=253, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9.-]*$')
    endpoint_port: int = Field(ge=1, le=65535)


class TailscaleDraft(ProviderDraft):
    provider: Literal['tailscale']
    tailnet: str = Field(min_length=1, max_length=253, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9.@_-]*$')


class NetBirdDraft(ProviderDraft):
    provider: Literal['netbird']
    management_url: str = Field(min_length=9, max_length=512)

    @field_validator('management_url')
    @classmethod
    def management_origin(cls, value: str) -> str:
        return https_origin(value)


ConnectDraft = Annotated[Union[WireGuardDraft, TailscaleDraft, NetBirdDraft], Field(discriminator='provider')]


def provider_catalog() -> list[dict]:
    return [
        {'id': provider.value, 'configuration': 'draft_only', 'can_activate': False,
         'server_adapter': 'not_implemented',
         'android_engine': 'compiled_poc' if provider == ProviderId.WIREGUARD else 'not_implemented',
         'enrollment': 'owner_approval_only' if provider == ProviderId.WIREGUARD else 'not_implemented',
         'reason': ('Inscrição e aprovação disponíveis em laboratório; instalação do gateway por implementar.'
                    if provider == ProviderId.WIREGUARD else 'Enrollment, transporte e isolamento ainda por validar.')}
        for provider in ProviderId
    ]
