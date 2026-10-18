# M2 — Servidor de laboratório e próximo ensaio

Atualização: 18-10-2026. NOVA Server 0.2.0-lab. Este incremento desenvolve o servidor; não entrega ainda o player NOVA Cinema.

**Fecho técnico:** assistente, gerador TrueNAS, imagem de instalação, healthchecks, schema versionado e recuperação cifrada implementados. **Aceitação física:** pendente; o proprietário confirmou que ainda não dispõe de acesso SSH. Não declarar M2 integralmente concluída antes desse ensaio.

[Guia TrueNAS, backup/restauro e atualização](M2_TRUENAS_RECUPERACAO.md).

## Implementado

- Criar o proprietário no NOVA Control usando o código de instalação de utilização única.
- Concluir o assistente Jellyfin pelo Control, com conta administrativa nova ou existente.
- Configurar uma biblioteca com as duas origens ou duas bibliotecas, escolhendo Filmes/Séries para cada uma.
- Verificar existência e listagem dos dois diretórios através do Jellyfin; pedir indexação e consultar contagens reais.
- Retomar uma operação interrompida sem voltar a definir a palavra-passe nem duplicar bibliotecas compatíveis.
- Recusar conflitos de nome/origem e mudanças da identidade Jellyfin; não apagar bibliotecas.
- Guardar identidade, última observação e contagens. Credenciais Jellyfin ficam apenas na memória da operação; há tentativa de logout no fim. Uma quebra de ligação pode impedir a revogação desse token no Jellyfin.
- Impedir duas configurações simultâneas com reserva SQLite válida entre processos e prazo limitado.
- Verificações prévias de Linux, arquitetura, Docker/Compose, portas, conta e caminhos. Instalador recusa estado parcial existente e sobreposição entre media e pasta privada NOVA.
- Gerador de YAML independente para Apps TrueNAS, com imagem por digest, UID/GID explícitos e mounts que recusam origens inexistentes.
- Inicialização do código de proprietário dentro do contentor, healthchecks e migração aditiva do schema NOVA 0 → 1; schemas futuros são recusados.
- Backup offline cifrado com age e restauro em pasta nova, sem media/cache, com revogação das sessões NOVA e tokens/chaves API Jellyfin. Recuperação M2 restrita a um único proprietário Jellyfin.
- Recolha de evidência de saúde, portas, utilizador e mounts sem expor credenciais, através de scripts/acceptance.py.

Uma listagem acessível não prova leitura de todos os ficheiros, montagem read-only, indexação completa ou reprodução. O painel mantém essa distinção e mostra a data da observação. Não há sincronização automática de palavras-passe entre NOVA e Jellyfin.

## Validação

Revisão executável final `39fb5874a53ba375a68d54f91bae2b3c64cead3a`: **oito jobs aprovados** na [CI 39125165626](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39125165626).

- Python 3.12 e 3.13: **133 testes aprovados por versão em Linux**; **127 aprovados e seis específicos Linux omitidos por versão em Windows**.
- HTTP real e Chromium aprovados nas quatro combinações; build/testes Android e auditoria das dependências também aprovados.
- Docker: criação do proprietário, configuração Jellyfin pelo Control, dois MP4 indexados em origens distintas, ausência de duplicados, mounts read-only e persistência após reinício.
- Recuperação: origem ausente recusada sem criar pasta vazia, recriação dos contentores, backup cifrado, recusa de cópia adulterada, restauro em pasta nova e rejeição das sessões/tokens anteriores.
- A imagem de instalação foi submetida novamente ao ensaio Docker completo **antes da publicação**. O digest publicado e a identidade da imagem ensaiada foram conferidos; leitura anónima do registry confirmada em 18-10-2026.

Imagem Linux amd64 validada:

```text
ghcr.io/sphinkz10/nova-core@sha256:5ba33012d87746792acc4f220dc3dc7e2985d974e71d7f960028056ea1aca16a
```

Estes resultados validam o laboratório automatizado. Não demonstram instalação, ACL, atualização, reinício físico ou restauro no TrueNAS do proprietário. Revisões posteriores exclusivamente documentais não alteram a imagem acima.

## Como ensaiar

Seguir [server/README.md](../server/README.md) num Linux de laboratório com Docker/Compose, usando duas pastas de media de teste. O pacote é código-fonte e configuração Compose; ainda não é uma App de catálogo TrueNAS.

No TrueNAS Community, começar pela recolha da versão/build e pela verificação de pré-requisitos, sem instalar pacotes no sistema base. A passagem para instalação depende do método suportado pela versão, permissões/ACL dos datasets e armazenamento persistente. Aprovação Docker genérica não certifica TrueNAS.

Continuam por executar no NAS: instalação Apps na versão concreta, ACL/datasets, reinício físico, falha de origem, atualização e restauro. Não há resultado físico deste TrueNAS registado nesta entrega.

## Quando podes instalar e testar

| Marco | O que podes testar | Critério de passagem |
|---|---|---|
| M2, incremento atual | Servidor em Linux de laboratório: proprietário, Jellyfin e bibliotecas | CI Docker aprovada; próximo passo físico: ensaio no TrueNAS com datasets de teste |
| M3 | Associar TV ao servidor por código, autorizar e revogar dispositivo | Identidade/TLS, expiração, repetição e revogação verificadas |
| M4 | Instalar APK NOVA Cinema e ver o primeiro filme local | Catálogo, comando, reprodução/seek/retoma na Xiaomi Box S2 e Chromecast Android TV |
| M0 + M5 | Usar WireGuard, Tailscale ou NetBird dentro da mesma APK | Túnel/HTTPS real por fornecedor, configuração no Control e isolamento do NAS |
| M6 | Instalação pessoal para utilização continuada | Pacotes assinados, atualização/restauro, testes dos dois aparelhos e estabilidade |
| M7 | Convidar familiares | Validações finais de segurança e revisão independente |

Os três motores já compilaram juntos na APK experimental e carregaram em emuladores API 26/35 com separação de processos. Isso ainda não fecha M0: faltam autenticação, túnel e HTTPS reais, mais hardware ARM/TV. A APK atual é de diagnóstico; a primeira APK para ver filmes chega em M4. A compatibilidade segue capacidades Android/ABI e não uma lista de marcas.

Não há uma data de calendário validada para M4/M6. A estimativa deve ser revista após fechar a associação/TLS e a primeira reprodução real; apresentar uma data agora esconderia esses bloqueios técnicos.
