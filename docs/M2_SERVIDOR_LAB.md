# M2 — Servidor de laboratório e próximo ensaio

Atualização: 18-10-2026. Este incremento desenvolve o servidor; não entrega ainda o player NOVA Cinema.

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

Uma listagem acessível não prova leitura de todos os ficheiros, montagem read-only, indexação completa ou reprodução. O painel mantém essa distinção e mostra a data da observação. Não há sincronização automática de palavras-passe entre NOVA e Jellyfin.

## Validação

Revisão de código `04fb3cfc4fc97979adc109506c411b105fd7441b`: 109 testes Python aprovados em Linux, incluindo as duas novas regressões de instalação. Teste HTTP real e navegador Chromium aprovados na CI; HTTP e Edge também aprovados localmente em Windows.

O primeiro ensaio Docker encontrou uma diferença concreta da API atual: `X-Emby-Token` já depende de autenticação legada. A integração foi corrigida para incluir `Token` no cabeçalho `Authorization: MediaBrowser`, sem ativar autenticação legada no servidor. Referência: [implementação oficial Jellyfin](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Server.Implementations/Security/AuthorizationContext.cs).

O teste Docker exige arranque, configuração via NOVA, dois MP4 sintéticos indexados com caminhos independentes, uma única biblioteca após repetição, escrita bloqueada nos mounts e persistência após reinício. Este teste passou na [CI 39123507587](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39123507587), job `compose-lab` / `117663780157`: duas origens indexadas, zero bibliotecas duplicadas e persistência após reinício.

## Como ensaiar

Seguir [server/README.md](../server/README.md) num Linux de laboratório com Docker/Compose, usando duas pastas de media de teste. O pacote é código-fonte e configuração Compose; ainda não é uma App de catálogo TrueNAS.

No TrueNAS Community, começar pela recolha da versão/build e pela verificação de pré-requisitos, sem instalar pacotes no sistema base. A passagem para instalação depende do método suportado pela versão, permissões/ACL dos datasets e armazenamento persistente. Aprovação Docker genérica não certifica TrueNAS.

Após esse ensaio, faltam reinício real do NAS, origem indisponível, atualização, cópia de segurança e restauro antes de fechar M2. Não há acesso ou resultado físico deste NAS registado nesta entrega.

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
