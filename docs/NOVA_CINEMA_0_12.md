# NOVA Cinema 0.12 — percurso de utilização na TV

A 0.12 reúne o acesso à conta, bibliotecas e reprodução numa interface para comando Android TV. É uma versão de teste com LAN e WireGuard nativo. A integração completa de Tailscale e NetBird continua pendente; a prova de transporte Tailscale não faz parte desta APK de distribuição.

## O que muda

- Início distingue a primeira configuração, entrada de conta e TV já associada. As opções WireGuard estão em **Ligação**.
- Catálogo em grelha, capas obtidas pela API NOVA autenticada, pesquisa, filtros de filmes/episódios e **Continuar a ver** por biblioteca/conta.
- Detalhe com sinopse, duração, temporada/episódio e retoma. Voltar preserva página, filtro e título selecionado.
- Player ocupa o ecrã; os controlos desaparecem durante a reprodução. Áudio, legendas, repetição e regresso ficam acessíveis pelo comando.
- Controlos do comando integrados na sessão de reprodução do Android, com foco de áudio e libertação da sessão ao sair do player.
- Uma reprodução pausada continua pausada depois de sair para outro ecrã e regressar. O progresso é limitado à duração declarada pelo servidor.
- Erros de ligação permitem repetir ou abrir as definições sem pedir imediatamente nova associação. Esquecer a TV exige confirmação na própria app.

## Capas e isolamento de contas

O servidor valida conta, biblioteca, caminho e ascendentes antes de pedir a imagem ao Jellyfin. Não devolve endereços ou credenciais do Jellyfin. São aceites apenas JPEG/PNG/WebP até 1 MiB; redirecionamentos e documentos SVG são recusados. A app valida as dimensões antes de descodificar, reduz a imagem e não cria cache em disco. Uma capa em falta mantém um cartão identificável pelo título.

A implementação usa a [API oficial de imagens Jellyfin](https://typescript-sdk.jellyfin.org/interfaces/models_api.ImageRequestParameters.html). O ensaio Docker inclui uma capa local seguindo a [organização de filmes Jellyfin](https://jellyfin.org/docs/general/server/media/movies/) e a consulta real de títulos retomáveis depois de gravar progresso.

## Instalar

A APK usa `com.novacinema.cinema`, versionCode 12 e a identidade de assinatura persistente das versões 0.9–0.11. Instalar como atualização, sem desinstalar a anterior. O Android conserva o estado se o pacote e a assinatura coincidirem. As provas de atualização automáticas usam uma chave temporária de CI; a chave de distribuição só é usada localmente.

Para capas e o filtro Continuar a ver, usar o servidor correspondente à entrega 0.12. O gerador continua destinado a uma instalação nova de teste. Um servidor 0.11 pode reproduzir o catálogo existente, mas não tem o novo endpoint de capas nem o filtro retomável.

Percurso: configurar TV → entrar na conta → escolher servidor → aprovar no Control → abrir biblioteca → escolher título → reproduzir. Para remoto: **Início → Ligação → Preparar WireGuard**, aprovação no Control, preparar novamente e ligar após o consentimento Android.

## Limites do lançamento

- Reprodução original (Direct Play); não há transcodificação adaptativa ou garantia de todos os codecs/HDR. Seleção de áudio/legendas depende das faixas incorporadas e do suporte Media3/aparelho; legendas externas ainda não são servidas pela API NOVA.
- WireGuard: preparação inicial na LAN, perfil de 24 horas renovável pelo túnel ativo. Expiração enquanto offline ainda exige voltar à LAN.
- Tailscale: transporte nativo provado separadamente; faltam configuração Control, associação e player na distribuição. NetBird não tem ainda esse percurso completo.
- TrueNAS Community, Xiaomi Box S2 e Chromecast/Android TV são alvos de aceitação. Os emuladores API 26/35 e o Docker não substituem os ensaios físicos, rede externa ou estabilidade prolongada.
- M5 e validações finais SEC-01…12 permanecem abertas. Esta entrega não constitui fecho da aplicação familiar completa.

Resultados, revisões e hashes da entrega constam de `NOVA_CINEMA_0_12_RESULTADOS.json` e do guia incluído ao lado da APK. Não usar resultados históricos como se tivessem sido executados nesta revisão.

## Validação desta entrega

**15/15 jobs aprovados**, reunindo a revisão executável `dde3a030216bfc7ff1d3d56dd5ce03eee25d3f40` e a instrumentação de capturas `a032cad34e225dfbc6d1bd2728aa8e04ce2f9e80`. A aplicação, núcleo e servidor são idênticos entre as duas revisões; a segunda trata apenas o aviso Android de primeira utilização do ecrã inteiro nas capturas. A permissão VPN continua a ser aprovada no diálogo real do sistema.

- [Base, Docker e imagem exata](https://github.com/Sphinkz10/NovaPlayer/actions/runs/40030609461): 8 jobs; Linux Python 3.12/3.13 com 402 aprovados + 1 exclusão em cada; Windows com 394 aprovados + 9 exclusões em cada; 203 verificações JVM, compilação e lint Android.
- [Assinatura/instalação/atualização](https://github.com/Sphinkz10/NovaPlayer/actions/runs/40030609443): API 26/35; identidade descartável na CI, recusa de assinatura diferente/downgrade e preservação do estado ao atualizar de 12 para 13.
- [Conta, catálogo/player e configuração LAN](https://github.com/Sphinkz10/NovaPlayer/actions/runs/40031550341): API 26/35, incluindo 12 critérios do player e capturas reais.
- [WireGuard nativo](https://github.com/Sphinkz10/NovaPlayer/actions/runs/40031550238): 38 verificações em cada API 26/35, com catálogo/vídeo, renovação e revogação.
- [Gateway gerado e recuperação](https://github.com/Sphinkz10/NovaPlayer/actions/runs/40030609441): 9 verificações remotas e 15 da recuperação cifrada. Jellyfin real confirma capas e consulta de títulos retomáveis.

A sessão de reprodução usa a [API MediaSession do Android](https://developer.android.com/reference/android/media/session/MediaSession). Os controlos são ativos apenas durante a reprodução em primeiro plano; não se acrescenta um serviço de reprodução em background.

APK final: `770f3d6c2a7e605b889bd368c8631fdb5dab562e211e2f7be29e41e666173108`. Build CI sem assinatura: `5e4ede95a4ef5ad86d2d1384a937b99552a499f1f1b20f04e13a21af3396a059` (idêntico nas duas APIs). A assinatura foi aplicada localmente com a identidade persistente. A instalação dessa assinatura nos aparelhos físicos continua por ensaiar.

As tentativas falhadas e respetivas correções estão conservadas no relatório JSON. Incluem amostragem de capa, variável do ensaio Docker, encaminhamento de teclas multimédia e o aviso de ecrã inteiro do Android 35. A aprovação desta entrega não apaga esses resultados.
