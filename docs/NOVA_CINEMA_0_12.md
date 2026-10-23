# NOVA Cinema 0.12 — percurso de utilização na TV

A 0.12 reúne o acesso à conta, bibliotecas e reprodução numa interface para comando Android TV. É uma versão de teste com LAN e WireGuard nativo. A integração completa de Tailscale e NetBird continua pendente; a prova de transporte Tailscale não faz parte desta APK de distribuição.

## O que muda

- Início distingue a primeira configuração, entrada de conta e TV já associada. As opções WireGuard estão em **Ligação**.
- Catálogo em grelha, capas obtidas pela API NOVA autenticada, pesquisa, filtros de filmes/episódios e **Continuar a ver** por biblioteca/conta.
- Detalhe com sinopse, duração, temporada/episódio e retoma. Voltar preserva página, filtro e título selecionado.
- Player ocupa o ecrã; os controlos desaparecem durante a reprodução. Áudio, legendas, repetição e regresso ficam acessíveis pelo comando.
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
