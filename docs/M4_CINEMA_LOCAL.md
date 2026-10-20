# M4 — NOVA Cinema local

Ponto único desta fase. A M3 de identidade e permissões mantém-se fechada em laboratório: [M3_FECHO.md](M3_FECHO.md).

## Resultado implementado

A APK 0.7-m4-lab acrescenta **Abrir NOVA Cinema** ao ecrã inicial e à associação. Uma conta Directory já aprovada escolhe uma biblioteca, consulta títulos, pesquisa, filtra filmes/episódios, abre a ficha e reproduz através do Media3. Há páginas de 24 títulos, comandos de reprodução, seleção de áudio/legendas incorporados e retoma da posição guardada no Jellyfin.

O cliente usa exclusivamente HTTPS NOVA com o certificado aprovado, sessão NOVA no cabeçalho e rotas de media fixas. Não recebe tokens Jellyfin, caminhos do NAS ou uma URL arbitrária de streaming. O Core volta a verificar utilizador, política Jellyfin e pertença do título à biblioteca atribuída. Não existe um proxy geral para a API Jellyfin.

O gateway transmite o ficheiro original por Range; esta entrega não pede transcodificação/remux. Fontes remotas, redirects, respostas comprimidas, intervalos múltiplos e conteúdo HTML são recusados. A revogação e a validade do dispositivo/conta são verificadas durante a transferência. Uma rotação do access token não invalida uma resposta de vídeo já autorizada. Novos pedidos exigem um token válido.

O player só funciona em primeiro plano. Ao sair liberta o player e envia a posição; durante reprodução envia progresso a cada dez segundos. Se a autorização ou a gravação do progresso falhar, pausa e apresenta recuperação. O Jellyfin aplica os seus limites de retoma, incluindo duração mínima e marcação de título visto.

## Critérios e evidências

| Critério | Validação |
|---|---|
| Catálogo e ficha limitados à biblioteca da conta | Testes de API; prova Docker preparada |
| Ficheiro original, Range e seek | Testes de API; prova Docker preparada |
| Progresso e retoma persistidos no Jellyfin | Testes de API; prova Docker preparada |
| D-pad → ficha → primeiro frame → seek → reabertura | Instrumentação preparada para emuladores API 26/35 |
| Reprodução física em Xiaomi Box S2 e Chromecast | Pendente; aparelhos não ligados a este ambiente |

Os resultados finais da execução são registados aqui depois dos gates. Um build ou um ficheiro de teste não certifica codecs, 4K, HDR, áudio multicanal ou desempenho das boxes.

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
