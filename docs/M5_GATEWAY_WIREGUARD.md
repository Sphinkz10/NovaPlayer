# M5 — Adaptador restrito WireGuard e capturas das apps

Incremento seguinte à [inscrição por TV](M5_INSCRICAO_WIREGUARD.md). A inscrição e a aprovação continuam separadas da configuração do gateway e de uma ligação autenticada. A instalação LAN disponível mantém a APK 0.9 e a imagem corrigida da entrega anterior.

## Adaptador implementado

- O Core exporta um conjunto público e consistente das TVs aprovadas através de `GET /api/v1/admin/connect/wireguard/plan`, exclusivo do proprietário. O plano expira em até 15 segundos, ou antes se uma associação expirar; exclui dispositivos revogados/expirados e contas desativadas. Não inclui chaves privadas, credenciais, interfaces ou rotas.
- O adaptador recebe a política local do operador, valida servidor/prazo e restringe endereços a um pool privado dedicado. Mantém endereços válidos já observados no kernel e atribui `/32` livres às TVs novas.
- Antes de alterar peers, verifica namespace diferente do chamador, interface WireGuard UP, alias de propriedade NOVA, chave pública do gateway e endereço local `/32` exatos. Recusa interface partilhada ou não identificada. A API HTTP não recebe um executor ou comandos.
- Remove peers desconhecidos e rotas excessivas antes de aplicar a lista aprovada. Uma repetição sem alterações não escreve novamente. A revogação faz desaparecer a TV do próximo plano; reconciliar esse plano remove o peer real.
- Confere novamente identidade e peers depois de aplicar. Um erro de aplicação, prazo ou leitura não é sucesso; tenta limpar apenas a interface que ainda corresponda à propriedade/identidade esperadas. Se o gateway ficar inacessível, a remoção não é anunciada como confirmada.

O adaptador não cria interfaces, não altera rotas/firewall, não manipula chaves privadas e não usa o Docker socket. `configuration_observed=true` confirma configuração lida do kernel; `handshake_verified=false` mantém explícito que configuração não prova tráfego. O ensaio de rede verifica handshake e HTTPS separadamente.

**Âmbito atual:** biblioteca usada por um único chamador de laboratório, com executor do namespace criado pelo harness. Não é um agente instalado no NAS. Falta o serviço contínuo, transporte autenticado de planos, confirmação no Control, leases persistentes quando o gateway é reconstruído e empacotamento compatível com TrueNAS. Os estados do Control continuam `gateway_state=not_verified` e `remote_access_enabled=false`.

## Capturas reais

Os ensaios passam a guardar o Control com uma inscrição aprovada e a app Android nas bibliotecas, catálogo, detalhe e reprodução. A app é executada num emulador Android horizontal; a reprodução usa vídeo sintético e uma fixture Jellyfin isolada. Não são mockups, conteúdo de produção ou ensaios físicos de Android TV.

As Activities de produção conservam `FLAG_SECURE`. Só a instrumentação debug de ensaio o desativa temporariamente nos quatro ecrãs de conteúdo sintético e volta a ativá-lo em `finally`. Não são capturados ecrãs com palavras-passe, tokens ou material privado. O gerador de capturas só corre num emulador CI descartável e repõe as dimensões/densidade no fim.

As [dez capturas originais](PRINTS_APPS.md) e a [proveniência com hashes](screenshots/PROVENIENCIA.json) acompanham esta revisão. A interface Cinema é provisória. No diagnóstico Control, a fixture Jellyfin devolve uma resposta incompleta; a captura não representa um servidor físico instalado.

## Resultados verificados

Código testado: `1b6402a2a40eefe995a528cecda9dc3064b4d793`. A CI executou o merge `71acb3dbb6ec47e6191082cab80b41890e4dc511`, cuja árvore é igual à do código testado. A atualização seguinte acrescenta apenas documentação, capturas e inventários.

- [CI principal](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39504206346): 8/8 jobs aprovados. Servidor: 343 testes por versão Python em Linux; 337 aprovados e 6 exclusões POSIX por versão em Windows. Kotlin: 203 testes. Build/lint Android, dependências, Docker e imagem do servidor aprovados.
- [WireGuard nativo](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39504206366): 25/25 verificações em API 26 e 35, incluindo remoção/correção de peers no kernel, idempotência, handshake real, HTTPS e revogação. API 26: RX 8452 B, TX 8700 B; API 35: RX 8340 B, TX 8700 B. O firewall registou 6 descartes em cada ensaio.
- [Associação, catálogo, player e capturas](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39504206356): API 26 e 35 aprovadas. A primeira tentativa API 35 falhou porque a janela de associação não ganhou foco; foi repetido apenas o job falhado, com as mesmas verificações, e passou. Esta repetição está registada na proveniência.
- [Distribuição e atualização](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39504206409): API 26 e 35 aprovadas.

As capturas são os PNGs originais, sem retoque. API 26 usa 640×320 e API 35 usa 1280×720. Estes ensaios não concluem a aceitação em TrueNAS, Xiaomi Box S2 ou Chromecast físicos.

## Próximo passo

Instalador/serviço do gateway com privilégios limitados, leases duráveis e confirmação real no Control; depois distribuição autenticada dos parâmetros públicos à TV e catálogo/player remoto. Tailscale e NetBird continuam obrigatórios e exigem as próprias jornadas nativas. A M3 de software permanece concluída; M5, aceitação física e SEC-01…12 continuam abertos.
