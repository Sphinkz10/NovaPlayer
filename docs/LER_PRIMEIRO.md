# NOVA — Guia das fontes atuais

**Atualização:** 20 outubro 2026. Começar por [M3_FECHO.md](M3_FECHO.md): critérios únicos, resultado consolidado e procedimento de ensaio. Aceitação física TrueNAS/TV continua separada.

**Trabalho atual:** [M4_CINEMA_LOCAL.md](M4_CINEMA_LOCAL.md) reúne catálogo, player e os critérios pendentes da primeira reprodução local.

As fontes atuais incluem M3 (`0.3.0-dev`): [associação de dispositivos](M3_ASSOCIACAO_DISPOSITIVOS.md), [cliente Android de laboratório](M3_CLIENTE_ANDROID.md) e [Directory privado](M3_DIRECTORY_LAB.md). A entrega M2 por digest permanece identificada no seu guia.

## Como usar este arquivo

1. Ler [M2_SERVIDOR_LAB.md](M2_SERVIDOR_LAB.md), [FASE_1_RESULTADOS.md](FASE_1_RESULTADOS.md) e [ESTADO_REAL.md](ESTADO_REAL.md).
2. Consultar [roadmap](ROADMAP_INSTALACAO_SERVER_TV_v0_2.md) e [contrato nativo](ADR_001_CONNECT_NATIVO.md); as especificações G0/F00/F01 são históricas onde divergirem destes documentos.
3. [../server/README.md](../server/README.md) contém instruções do servidor de laboratório. Para Apps e backup/restauro, seguir [M2_TRUENAS_RECUPERACAO.md](M2_TRUENAS_RECUPERACAO.md).
4. [../connect/README.md](../connect/README.md) contém build Android e testes.
5. [../design/LINKS_FIGMA.md](../design/LINKS_FIGMA.md) aponta para os designs remotos.
6. `../archives/` preserva os ZIPs originais. `../archives/inventory-original/` preserva os manifests históricos, cujos caminhos se referiam à organização antiga.
7. O inventário atual usa caminhos relativos à raiz do repositório. Validar com `python scripts/inventory.py` a partir dessa raiz. Para regenerar após alterações: `python scripts/inventory.py --write`. Exclui os próprios manifests, dados, segredos e resultados de build ignorados por Git.

## Limites do pacote

- **Não** é uma única instalação pronta a usar: são fontes de código e documentos.
- **Não** contém ficheiro `.fig` editável offline; o original reside no Figma.
- O build produz a APK 0.7-m4-lab, com login Directory, associação, catálogo e player local em validação. O Directory continua separado; instalação LAN guiada, túneis completos e aceitação física permanecem pendentes.
- O pacote servidor é apenas uma primeira prova local, **não instalar em produção nem expor na Internet**.
- WireGuard, Tailscale e NetBird compilaram juntos numa APK experimental. A APK normal ainda inclui apenas WireGuard; nenhum dos três tem a jornada remota completa aprovada.

Os ZIPs originais não recebem as correções atuais. Usar as fontes atuais ou o pacote NOVA Server 0.2.0-lab; a pasta interna `NOVA_Fase1` mantém o nome histórico do empacotador.
