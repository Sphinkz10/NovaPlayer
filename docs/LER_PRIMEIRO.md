# NOVA — Guia das fontes atuais

**Atualização:** 17 outubro 2026, primeira fase de implementação após auditoria.

## Como usar este arquivo

1. Ler [FASE_1_RESULTADOS.md](FASE_1_RESULTADOS.md) e [ESTADO_REAL.md](ESTADO_REAL.md).
2. Consultar [roadmap](ROADMAP_INSTALACAO_SERVER_TV_v0_2.md) e [contrato nativo](ADR_001_CONNECT_NATIVO.md); as especificações G0/F00/F01 são históricas onde divergirem destes documentos.
3. [../server/README.md](../server/README.md) contém instruções do servidor de laboratório.
4. [../connect/README.md](../connect/README.md) contém build Android e testes.
5. [../design/LINKS_FIGMA.md](../design/LINKS_FIGMA.md) aponta para os designs remotos.
6. `../archives/` preserva os ZIPs originais. `../archives/inventory-original/` preserva os manifests históricos, cujos caminhos se referiam à organização antiga.
7. O inventário atual usa caminhos relativos à raiz do repositório. Validar com `python scripts/inventory.py` a partir dessa raiz. Para regenerar após alterações: `python scripts/inventory.py --write`. Exclui os próprios manifests, dados, segredos e resultados de build ignorados por Git.

## Limites do pacote

- **Não** é uma única instalação pronta a usar: são fontes de código e documentos.
- **Não** contém ficheiro `.fig` editável offline; o original reside no Figma.
- O build produz uma APK de diagnóstico; NOVA Directory, associação e vídeo ainda não estão implementados.
- O pacote servidor é apenas uma primeira prova local, **não instalar em produção nem expor na Internet**.
- WireGuard, Tailscale e NetBird são requisitos nativos. Só o motor WireGuard está compilado; nenhum dos três tem a jornada remota completa aprovada.

Os ZIPs originais não recebem as correções atuais. Usar as fontes atuais ou o pacote de fase 1.
