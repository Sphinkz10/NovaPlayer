# M4 — NOVA Cinema local

Ponto único desta fase. **Catálogo e reprodução aprovados em laboratório em 20-10-2026. A M4 continua aberta para instalação LAN e aceitação física.** A M3 de identidade e permissões mantém-se fechada em laboratório: [M3_FECHO.md](M3_FECHO.md).

**Novo trabalho LAN:** gerador de instalação nova e bootstrap nativo da TV implementados, em validação. [Instalação LAN](M4_INSTALACAO_LAN.md) descreve este perfil; a entrega 0.7 abaixo continua a identificar a prova anterior.

## Resultado implementado

A APK 0.7-m4-lab acrescenta **Abrir NOVA Cinema** ao ecrã inicial e à associação. Uma conta Directory já aprovada escolhe uma biblioteca, consulta títulos, pesquisa, filtra filmes/episódios, abre a ficha e reproduz através do Media3. Há páginas de 24 títulos, comandos de reprodução, seleção de áudio/legendas incorporados e retoma da posição guardada no Jellyfin.

O cliente usa exclusivamente HTTPS NOVA com o certificado aprovado, sessão NOVA no cabeçalho e rotas de media fixas. Não recebe tokens Jellyfin, caminhos do NAS ou uma URL arbitrária de streaming. O Core volta a verificar utilizador, política Jellyfin e pertença do título à biblioteca atribuída. Não existe um proxy geral para a API Jellyfin.

O gateway transmite o ficheiro original por Range; esta entrega não pede transcodificação/remux. Fontes remotas, redirects, respostas comprimidas, intervalos múltiplos e conteúdo HTML são recusados. A revogação e a validade do dispositivo/conta são verificadas durante a transferência. Uma rotação do access token não invalida uma resposta de vídeo já autorizada. Novos pedidos exigem um token válido.

O ensaio Docker revelou que `Ids` pode sobrepor-se ao filtro `ParentId` do Jellyfin. O NOVA exige agora o caminho sob a origem read-only verificada e a cadeia de antecessores com a biblioteca autorizada. A origem alternativa do ficheiro também é verificada. Os testes reproduzem deliberadamente a resposta permissiva do Jellyfin; ficha, vídeo e escrita de progresso de outro título têm de ser recusados. Esta falha pertenceu ao novo gateway M4, não às rotas de autorização de biblioteca M3.

O player só funciona em primeiro plano. Ao sair liberta o player e envia a posição; durante reprodução envia progresso a cada dez segundos. Se a autorização ou a gravação do progresso falhar, liberta o player/buffer e apresenta recuperação, preservando a posição em memória. O Jellyfin aplica os seus limites de retoma, incluindo duração mínima e marcação de título visto.

## Critérios e evidências

| Critério | Validação |
|---|---|
| Catálogo e ficha limitados à biblioteca da conta | Aprovado em API e Jellyfin real Docker, incluindo consulta permissiva por ID |
| Ficheiro original, Range e seek | Aprovado em API/Docker e decode Media3 nos dois emuladores |
| Progresso e retoma persistidos no Jellyfin | Aprovado no Jellyfin real; reabertura aprovada nos emuladores com fixture isolada |
| D-pad → ficha → primeiro frame → seek → reabertura | Aprovado nos emuladores API 26 e 35 |
| Reprodução física em Xiaomi Box S2 e Chromecast | Pendente; aparelhos não ligados a este ambiente |

Revisão executável verificada: `53407fe0ef496a7e194a344d74c13fba3d33027b`. A CI testa a árvore do merge do PR, confirmada igual à árvore desta revisão. [CI 8/8](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39396695163) e [Android API 26/35](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39396695151) aprovados. Linux Python 3.12/3.13: **276/276** cada; Windows: **270 aprovados + 6 POSIX ignorados** cada; Kotlin: **203**; lint aprovado. Docker repetido sobre a imagem exata antes da publicação.

Em cada emulador passaram 11 fases de associação anteriores, 11 fases M3 e os 8 checks M4. O vídeo sintético é H.264/AAC; o seek exige um salto de pelo menos nove segundos em cinco segundos, e a retoma exige novo primeiro frame. O Android usa um Jellyfin HTTP fixture isolado; o teste Docker usa Jellyfin real. Estes ensaios são distintos e não equivalem a NAS/TV físicos.

Uma execução intermédia API 26 falhou no foco imediato do botão de confirmação, antes da associação. O harness passou a esperar por foco real, mantendo o D-pad e as verificações de segurança. A revisão final passou nos dois níveis sem recorrer a clique direto ou relaxar TLS/permissões.

Imagem `linux/amd64`: `ghcr.io/sphinkz10/nova-core@sha256:2c7a51e0dbfd4b85735aaf264b97078d5b3113700125353abfeba5b86ee1bb26`.

APK entregue: a testada no API 35, versão `0.7-m4-lab`, pacote `com.novacinema.connect.poc`, min SDK 26, target 35, assinatura debug v2. SHA-256: `38160fd4ebe32ad5da2438680058b3e25d7c4b5307ccb6628254b8cfbac99444`. API 26 testou um build equivalente com a própria assinatura de CI. Não substituir este APK por outro build sem registar a sua proveniência.

Um build ou um ficheiro de teste não certifica codecs, 4K, HDR, áudio multicanal ou desempenho das boxes.

## Ensaio

1. Usar o mesmo laboratório privado e bootstrap Directory do [guia M3](M3_FECHO.md). Atualizar o Core e a APK em conjunto; o cliente M3 anterior não contém o player.
2. Confirmar no Control que o proprietário configurou o Jellyfin, indexou as origens e atribuiu bibliotecas à conta.
3. Entrar com Directory, aprovar a TV e abrir **NOVA Cinema**. Começar por MP4 H.264/AAC conhecido, com pelo menos dez minutos, para verificar retoma segundo as regras Jellyfin.
4. Escolher um título, reproduzir, pausar e avançar. Sair para a ficha, esperar a gravação da posição e voltar a abrir **Retomar**.
5. Repetir em A/B com contas autorizadas e confirmar que o título de uma biblioteca não atribuída não aparece nem pode ser aberto.
6. Revogar o dispositivo no Control durante a reprodução. Confirmar pausa/interrupção e recusa de novas autorizações; pode haver vídeo já em buffer no aparelho.

O launcher da API de cliente continua limitado a 127.0.0.1. O laboratório na TV usa o encaminhamento ADB descrito na M3. Ainda falta a entrega de instalação LAN guiada no TrueNAS. Não anunciar instalação familiar concluída por existir um player no laboratório.

## O que falta para fechar a M4

- Prova de vídeo e retoma em cada aparelho físico e no TrueNAS, com identificação de sistema/formatos.
- Empacotamento da instalação LAN de cliente/Directory, mantendo administração separada e HTTPS.
- Consolidar experiência de TV, capa/banner de produto e assinatura definitiva de atualização.
- Medir formatos e decidir as rotas autorizadas de remux/conversão; legendas externas e séries por temporada ainda não fazem parte desta primeira UI.

WireGuard, Tailscale e NetBird nativos continuam na M5. O catálogo/player local não fecha as suas jornadas remotas. SEC-01…12 continuam sem aceitação final.

## Fontes de implementação

- [Media3 — versões e API](https://developer.android.com/jetpack/androidx/releases/media3): versão 1.9.4 fixada para a base Kotlin/SDK existente.
- [Jellyfin ItemsController](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/ItemsController.cs): consulta por utilizador, biblioteca e IDs.
- [Jellyfin VideosController](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/VideosController.cs): ficheiro original com Static.
- [Jellyfin PlaystateController](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/PlaystateController.cs): início, progresso e fim de reprodução.
