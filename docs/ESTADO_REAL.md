# Estado atual — 20 outubro 2026

O ponto único para concluir a M3 é [M3_FECHO.md](M3_FECHO.md). Os quatro guias M3 anteriores são registos de incrementos; não devem ser usados para decidir o estado atual.

| Marco | Estado e limite |
|---|---|
| M1 — base | Implementada e testada |
| M2 — servidor | Software aprovado em Docker, com instalação por digest e recuperação cifrada. Aceitação no TrueNAS físico pendente |
| M3 — identidade e permissões | Concluída no software de laboratório: login Directory na TV, prova assinada de conta, aprovação, bibliotecas Jellyfin limitadas, renovação e revogação. Sete critérios aprovados; CI 8/8, API 26/35 e Docker real. Ver evidências no documento único |
| M4 — primeiro filme local | Catálogo, pesquisa, ficha, player Media3, faixas incorporadas e progresso implementados; validação integrada em curso. Instalação LAN guiada e aparelhos físicos pendentes. [Ponto único M4](M4_CINEMA_LOCAL.md) |
| M5 — ligação remota | WireGuard, Tailscale e NetBird nativos continuam obrigatórios. Compilação experimental dos três motores não prova túneis funcionais |
| M6/M7 — utilização familiar | Exigem matriz física, rede externa e validações finais de segurança |

Alvos: TrueNAS Community e Android TV/Google TV API 26+, incluindo Xiaomi Box S2 e Chromecast. Os emuladores não certificam os aparelhos físicos, codecs, HDR ou desempenho.

A M3 permite ensaiar identidade e permissões. A M4 acrescenta catálogo/player ao laboratório, com limites registados no seu documento único. A utilização remota com escolha dos três fornecedores depende da M5. O NAS e as boxes ainda não foram usados nesta sessão.
