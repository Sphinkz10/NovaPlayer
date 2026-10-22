# Estado atual — 22 outubro 2026

O ponto único para concluir a M3 é [M3_FECHO.md](M3_FECHO.md). Os quatro guias M3 anteriores são registos de incrementos; não devem ser usados para decidir o estado atual.

| Marco | Estado e limite |
|---|---|
| M1 — base | Implementada e testada |
| M2 — servidor | Software aprovado em Docker, com instalação por digest e recuperação cifrada. [Imagem atualizada](M5_INSCRICAO_WIREGUARD.md#correções-no-servidor-lan) corrige arranque concorrente SQLite e atualiza `certifi`. Aceitação no TrueNAS físico pendente |
| M3 — identidade e permissões | Concluída no software de laboratório: login Directory na TV, prova assinada de conta, aprovação, bibliotecas Jellyfin limitadas, renovação e revogação. Sete critérios aprovados; CI 8/8, API 26/35 e Docker real. Ver evidências no documento único |
| M4 — primeiro filme local | Instalação LAN, configuração TV, catálogo/player e recuperação integrada aprovados em laboratório. [Distribuição atual](M4_DISTRIBUICAO_ANDROID.md): pacote NOVA Cinema próprio, não depurável e com assinatura persistente offline; manter a chave privada e uma cópia de recuperação separada. Aceitação física pendente |
| M5 — ligação remota | [Gateway Docker e percurso WireGuard](M5_GATEWAY_CONTENTOR.md), com [renovação pelo túnel e recuperação dos cinco serviços](M5_RENOVACAO_RECUPERACAO.md). [Tailscale nativo](M5_TAILSCALE_NATIVO.md) já passou a prova de transporte HTTPS nas APIs 26/35, incluindo reconexão e revogação. Faltam configuração/instalação pelo Control e player Tailscale, jornada NetBird e descoberta/reconexão após expiração offline |
| M6/M7 — utilização familiar | Exigem matriz física, rede externa e validações finais de segurança |

Alvos: TrueNAS Community e Android TV/Google TV API 26+, incluindo Xiaomi Box S2 e Chromecast. Os emuladores não certificam os aparelhos físicos, codecs, HDR ou desempenho.

A M3 permite ensaiar identidade e permissões. O perfil M4 LAN prepara uma instalação nova e configuração na própria TV, sem ADB para provisionar o Directory. O PC gera o pacote; a transferência inicial e os ACL no NAS são passos do proprietário. A utilização remota com escolha dos três fornecedores depende da M5. O NAS e as boxes ainda não foram usados nesta sessão.
