# NOVA Cinema — G0 · Especificação Mestre UX e Produto

**Versão:** 1.0 · **Data:** 11-10-2026 · **Estado:** baseline documental, pendente de validação em protótipo e em Jellyfin real  
**Âmbito:** primeira aplicação TV, cinema e séries · **Sem código nem alteração ao Figma**

## 0. Leitura rápida

**Visão:** cliente multimédia privado com aspeto premium, navegação por comando e reprodução descodificada na TV quando o ficheiro é compatível. Servidor Jellyfin + TrueNAS, integração independente para a NOVA.  
**Entrega principal do G0:** identidade das rotas, estados de cada ecrã, percursos de utilizador, regras de foco e regresso, contratos de dados, exceções e critérios de aprovação.  
**Estado honesto:** especificação escrita; 0 ecrãs finais, 0 testes reais, 0 aplicações instaláveis.

### 0.1 Decisões fechadas

| Tema | Baseline |
|---|---|
| Home | Híbrida: hero compacto, «A seguir», descoberta e recentes |
| Descoberta | Um filme principal + duas alternativas; promoção sem iniciar reprodução |
| Preferências Discovery | Até 120 min inclusive; Surpreende-me; não vistos nem iniciados |
| Entrada Discovery | Inicial: apresentar filtros. Regresso: resultados diretos com filtros guardados |
| Reprodução | Direct Play antes de Remux, depois áudio-only quando autorizado; conversão de vídeo só com autorização explícita e permissões reais |
| Tráfego de vídeo | App → Jellyfin → NAS; NOVA Core não transporta vídeo |
| Perfis | Um utilizador/identidade Jellyfin autorizada por perfil na versão inicial |
| Dispositivo inicial | Protótipo de referência Android TV / Google TV **provisório**, até confirmar a TV real |
| Admin | Usar o Jellyfin inicialmente; NOVA Control avançado fora do MVP |
| Plataforma | Prioridade TV, com serviços desacoplados de componentes visuais e motor de player |

### 0.2 Fora do MVP inicial

Importador NOVA Control automatizado, downloads offline, casting entre TVs, telemóvel como comando, DRM, IPTV, filmes comerciais em streaming, perfis visuais partilhando uma credencial Jellyfin, sincronização multi-servidor, IA generativa, pré-geração pesada de previews.

---

## 1. Arquitetura de informação: rotas e transições

```text
START
 ├─ sem servidor associado → TV-01 Ligação
 ├─ sessão expirada → TV-01 Reautenticação contextual
 ├─ perfil por selecionar → TV-02 Perfis
 └─ sessão válida → TV-03 Home

TV-03 HOME
 ├─ TV-04 Filmes ────────> TV-07 Ficha filme ────> TV-13 Player
 ├─ TV-05 Séries ────────> TV-08 Ficha série ─────> TV-09 Episódios ─> TV-13
 ├─ TV-06 Pesquisa ──────> TV-07 ou TV-08 ──────> TV-13
 ├─ TV-10 Descoberta ────> TV-07 ───────────────> TV-13
 │      └─ botão Ver agora ──────────────────────> TV-13
 ├─ TV-11 Minha lista ────> TV-07 ou TV-08 ─────> TV-13
 ├─ TV-12 Coleções ───────> TV-07 / TV-08 ──────> TV-13
 └─ TV-14 Definições / TV-02 Perfis

TV-15 Estados de sistema = camada contextual sobre rota atual; nunca um beco sem saída.

TV-13 Player → Voltar → rota/posição de origem (Home, ficha ou Discovery).
```

**Regra:** navegar para um detalhe empilha a rota atual com o contexto; regressar restaura elemento focado, ordenação, filtros, scroll e seleção. Redirecionamentos de autenticação mantêm o destino original se ainda autorizado.

**Deeplink:** abrir uma ficha a partir de notificação ou outra aplicação constrói uma pilha lógica com Home como base, para que Voltar nunca termine numa página inexistente.

**Troca de perfil:** invalida dados de catálogo que não correspondam às novas permissões, limpa pilhas de navegação privadas e refaz a Home para o novo perfil. Não conserva seleção privada do anterior.

---

## 2. Contrato das 15 vistas de TV

Em todas as vistas: carregamento, vazio, dados parciais, offline, falha recuperável e sessão expirada devem ter tratamento. Nem todos aparecem como ecrã independente; podem ser estados de um mesmo componente.

| ID | Vista | Entrada normal | Foco inicial | Saídas principais | Sem dados / erro | Voltar |
|---|---|---|---|---|---|---|
| TV-01 | Ligação | Primeira execução / credencial inválida | Servidor descoberto ou ação «Procurar» | Associação, endereço manual, login alternativo | Repetir, diagnóstico LAN, entrada manual | Sair para launcher sem ciclo |
| TV-02 | Perfis | Primeiro acesso / trocar utilizador | Último perfil autorizado, se não protegido | Home, autenticar outro perfil | Sem perfil: associar conta | Ecrã anterior, exceto entrada inicial |
| TV-03 | Home | Abertura habitual | Primeiro «A seguir» se houver; senão hero | Filmes, Séries, Pesquisa, Descoberta, player, listas | Biblioteca vazia: introdução + abrir catálogo | Saída conforme convenção da plataforma |
| TV-04 | Filmes | Menu / Home | Chip ativo ou primeiro poster, conforme última posição | Filtros, ficha, pesquisa | Sem resultados: limpar/editar filtros | Preservar scroll/filtros na Home |
| TV-05 | Séries | Menu / Home | Série focada anteriormente / primeira série | Ficha série, pesquisa, filtros | Sem séries: explicação, Home | Preservar contexto |
| TV-06 | Pesquisa | Menu / ícone | Campo de texto | Resultado filme, série ou coleção | Sem resultados: corrigir consulta | Manter texto e resultados enquanto vigente |
| TV-07 | Ficha filme | Catálogo, pesquisa, descoberta, coleções | «Reproduzir» se elegível, senão primeira ação disponível | Player, lista, escolher versão, relacionados | Indisponível: mensagem e regresso | Retorna à origem exata |
| TV-08 | Ficha série | Catálogo, pesquisa, lista | «Continuar» ou «Começar série» | Episódios, Player direto, lista | Sem episódios: ficha informativa | Retorna à origem exata |
| TV-09 | Episódios | Ficha série | Primeiro episódio relevante (continuação/próximo) | Player, outra temporada, detalhe | Episódio em falta: explica, não inventa | Volta à série mantendo temporada |
| TV-10 | O que vamos ver? | Home / Descobrir | Filme principal ou filtro inicial na primeira entrada | Promover B/C, detalhes, reproduzir, novo trio, editar filtros | 0/1/2 candidatos: layout e recuperações próprias | Home restaurada sem perder sessão de sugestões |
| TV-11 | Minha lista | Home / menu | Primeiro título | Ficha ou remover | Lista vazia: convite para guardar | Rota anterior |
| TV-12 | Coleções | Home / Filmes | Primeira coleção/título | Ficha de filme/série | Coleção vazia/sem acesso: explicação | Rota anterior com foco |
| TV-13 | Player | Ficha, Home, Descoberta, próximo episódio | Vídeo sem overlay; foco só ao abrir controlos | Pause, seek, áudio, legendas, próxima entrada, sair | Ver matriz de falhas de playback | Regressa à origem e guarda progresso |
| TV-14 | Definições | Menu / perfil / player | Secção que abriu a vista | Idioma, player, sessão, dispositivo | Falha de gravação: manter valor anterior | Sem perdas de preferências anteriores |
| TV-15 | Estado de sistema | Interrupção contextual | «Tentar novamente» ou ação segura | Repetir, editar ligação, voltar | Nunca tela infinita sem saída | Contexto anterior quando viável |

### Componentes partilhados, não rotas novas

`FilterPanel`, `SortingMenu`, `SubtitlePicker`, `AudioPicker`, `VersionPicker`, `ConfirmationDialog`, `PlaybackError`, `ProfileAccessGate`, `ConnectionStatus`, `LoadingSkeleton`, `FocusRing`, `EmptyState`, `Toast`.

---

## 3. Contrato único de navegação D-pad

### 3.1 Fora do player

- **Esquerda/direita:** próximo/anterior elemento na mesma linha ou grupo.
- **Cima/baixo:** troca de linha ou zona sem saltos arbitrários; preserva a coluna mais próxima.
- **OK:** ativa exclusivamente o controlo focado.
- **Voltar:** fecha o overlay superior; senão desempilha a rota, restaurando contexto.
- **Home do comando:** controlado pelo sistema operativo; não o capturamos como saída própria.
- **Sem foco oculto:** todos os controlos essenciais são atingíveis com quatro direções.
- **Foco visível:** outline de elevado contraste e diferença de tamanho/fundo. Nunca confiar só na cor.

### 3.2 Player: máquina de estados de interação

| Estado | OK | ←/→ | ↑/↓ | Voltar |
|---|---|---|---|---|
| Vídeo sem overlay | Pausar/retomar | Salto de 10 s, quando o player suporta | Revela controlos | Sair e regressar à origem |
| Overlay visível | Ativar controlo focado | Mover foco entre ações | Mover foco entre grupos | Fechar overlay |
| Barra temporal ativa | Confirmar posição | Ajustar posição | Alterar zona conforme layout | Cancelar busca |
| Seletor áudio/legendas | Confirmar escolha | Se aplicável, navegar grupos | Navegar faixas | Fechar seletor |
| Erro recuperável | Ativar ação focada | Navegar ações | Navegar ações | Voltar à ficha/contexto |

**Consistência:** Play/Pause dedicado executa sempre pause/resume se existir; seleção de outra faixa não desencadeia vídeo transcode proibido. Ações relacionadas com seek devem ter feedback visual; saltos e barra temporal são modos diferentes.

### 3.3 Overlays e prioridades

Ordem de precedência para Voltar: `diálogo de confirmação` → `seletor de idioma/versão` → `painel de filtros` → `controlos do player` → `rota atual`. Nunca abrir dois overlays concorrentes. O foco anterior ao overlay é memorizado e restaurado quando fecha.

### 3.4 Persistência do contexto

Contexto mínimo por rota: `routeId`, `sourceRoute`, `itemId`, `sectionId`, `focusedElementId`, `scrollOffset`, `activeFilters`, `sort`, `selectedSeason`, `query`, `selectedVariant`. Não persistir tokens ou dados sensíveis nesse estado de navegação.

Discovery adicional: `candidateIds`, `primaryId`, `recentlyShownIds`, `filterSnapshot`, `generatedAt`, `profileId`. Ao mudar perfil, descartar. Ao voltar de um detalhe, não recalcular trio silenciosamente.

---

## 4. As 12 jornadas essenciais com prova de conclusão

| ID | Jornada | Entrada → execução | Saída ideal | Recuperação verificável |
|---|---|---|---|---|
| J01 | Instalação | TV-01, descoberta, código, autorização | TV-02/TV-03 | Sem descoberta: endereço manual; código expirado: renovar |
| J02 | Abertura diária | Abrir com sessão válida | TV-03 sem login repetido | Sessão revogada: login preservando intenção |
| J03 | Retoma filme | Home «A seguir», reprodução | TV-13 no ponto correto | Ficheiro removido: ficha informativa |
| J04 | Filtrar filme | TV-04, chips e filtros, ficha | TV-13 / TV-07 | 0 resultados: remover filtro individual |
| J05 | Ver série | TV-05, TV-08, TV-09, player | Episódio correto | Episódio em falta: opção explícita de selecionar outro |
| J06 | Descoberta | TV-03 → TV-10 com 120min/não visto, B/C | TV-13 ou TV-07 | 0/1/2 candidatos; novo trio sem repetição enquanto houver opções |
| J07 | Pesquisa | TV-06, termo, resultado | TV-07/TV-08 | Sem resultados: editar termo; ao voltar texto preservado |
| J08 | Áudio/legendas | TV-13 → seletor → escolher | Continuar vídeo | Incompatível: outra faixa ou mensagem sem converter vídeo ocultamente |
| J09 | Outro dispositivo | Sair no cliente A, abrir B | Retoma sincronizada | Estado local mais recente ainda pendente: reconciliar sem sobrepor silenciosamente |
| J10 | Codec incompatível | Clicar Play, negociar | Direct Play/Remux/áudio-only | Se video transcode seria necessário: perguntar ou bloquear segundo política |
| J11 | Servidor offline | Perda LAN/servidor | Reconectar e retomar quando possível | Manter contexto/cache sem simular reprodução offline |
| J12 | Mudar perfil | TV-02, selecionar conta autorizada | Home filtrada por permissões novas | Perfil protegido: autenticação; dados antigos limpos |

**Cobertura:** toda a jornada tem entrada, saída e pelo menos uma recuperação especificada. Ainda não significa que o percurso foi testado.

---

## 5. Descoberta — especificação funcional de candidatos 1+2

### 5.1 Regras não negociáveis

- Filme autorizado para o perfil ativo, disponível, com duração conhecida ≤ 120 minutos.
- Não marcado como visto; sem progresso de reprodução relevante. Nunca tratar «desconhecido» como «não visto» sem verificação.
- Várias versões físicas formam um só candidato lógico; a versão é escolhida no player separadamente.
- Três filmes diferentes, se existirem pelo menos três elegíveis; com 1 ou 2, apresentar layout com 1 ou 2.
- «Surpreende-me» não filtra género; favorece diversidade ao compor o conjunto.
- Não repetir títulos numa sessão enquanto existirem candidatos ainda não apresentados.
- Não alterar automaticamente os filtros se o resultado for vazio.

### 5.2 Produção do trio

1. Selecionar itens por `Movie` e conta ativa.
2. Verificar disponibilidade, permissões, duração e estado de visualização.
3. Agrupar versões; calcular relevância com dados de catálogo e histórico.
4. Selecionar principal mais equilibrada.
5. Selecionar B para exploração; C para contraste, penalizando proximidade excessiva com A e B.
6. Guardar resultados de sessão e razões baseadas apenas em factos disponíveis.
7. «Outras sugestões» mantém candidatos restantes e deixa recuperar o trio anterior durante a sessão, quando viável.

### 5.3 Pesos exploratórios, **não validados**

Afinidade 30%; exploração 20%; avaliações com confiança 20%; compatibilidade 15%; novidade 15%. Usar normalização e tratamento neutro para valores inexistentes. Revisitar os pesos nos testes de pertinência; não apresentá-los como probabilidade real de gostar de um filme.

### 5.4 Compatibilidade prevista versus confirmada

Uma ficha pode indicar «Direct Play provável». Apenas depois de iniciar uma sessão e observar o método real poderá indicar «Direct Play confirmado». Se a reprodução exigir conversão de vídeo, não iniciar sem política/consentimento aplicáveis.

---

## 6. Dados: fonte de verdade e limites de responsabilidade

| Função | Fonte de verdade | Necessidade NOVA | Validação técnica pendente |
|---|---|---|---|
| Catálogo e tipo | Jellyfin | Consultas e paginação | Comportamento e campos `GetItems` em Jellyfin 12 |
| Duração/ano/género/imagens | Jellyfin | Cards, filtros, descoberta | Disponibilidade e nomes concretos no schema atual |
| Histórico visto/progresso | Jellyfin por utilizador | A seguir, não vistos, retoma | Atualização e tratamento de conflitos entre clientes |
| Temporadas/episódios | Jellyfin | Ficha série/Next Up | Episódios especiais, múltiplas versões e ausências |
| Permissões/autenticação | Jellyfin | Perfis reais, biblioteca autorizada | Quick Connect, token, revogação, armazenamento seguro |
| PlaybackInfo/MediaSources | Jellyfin + player | Negociação e seleção de versão | Perfil de codecs/legendas conforme dispositivo real |
| Descoberta e filtros guardados | NOVA local/serviço opcional | Trios e preferências NOVA | Persistência cross-device para V1.1 |
| Tráfego de media | Jellyfin → player da TV | Vídeo não atravessa o NOVA Core | Direct Play observado no dashboard e na rede |
| Sistema de ficheiros | TrueNAS | Biblioteca final e backups | Mounts/permissões na instalação real |

**Atenção Jellyfin 12:** a versão 12.0 alterou o comportamento de `GetItems`, a geração OpenAPI e formas obsoletas de autenticação; Quick Connect para iniciar usa `POST /QuickConnect/Initiate`. O contrato exato precisa de ser testado com a versão do servidor real, sem codificar contra endpoints retirados.

**Contas:** um perfil com histórico e permissões próprias corresponde a um utilizador Jellyfin próprio no MVP. Uma TV pode guardar sessões de perfis explicitamente autorizados, mas não mostrar nem reutilizar credenciais administrativas em contas familiares.

**Segurança:** HTTPS fora de casa, armazenamento seguro de tokens, pedidos autorizados por utilizador, separação da administração e revogação de dispositivos. Cache privado particionado por conta. Não expor endpoints administrativos no cliente TV.

---

## 7. Matriz de estados globais e recuperação

| Estado | Visual | Ação principal | Preservar |
|---|---|---|---|
| Loading | Skeleton no lugar correto; sem flashes | Normalmente nenhuma | Foco e layout |
| EmptyLibrary | Explicação, ligação/configuração | Abrir fontes/biblioteca | Sessão |
| EmptySearch | Mensagem + termo procurado | Editar texto | Texto e filtros |
| EmptyDiscovery | Respeitar restrições originais | Editar duração/estado | Preferências |
| PartialData | Capa placeholder/sem sinopse | Abrir ficha | Conteúdos disponíveis |
| Offline | Servidor indisponível, sem prometer playback | Tentar novamente | Navegação e credencial |
| Unauthorized | Sessão inválida/revogada | Reautenticar | Rota pretendida não privada |
| Restricted | Sem permissão de biblioteca | Mudar perfil autorizado | Isolamento de dados |
| MissingFile | Conteúdo indexado mas ficheiro indisponível | Atualizar/voltar | Contexto origem |
| IncompatibleMedia | Video/áudio/legenda não suportados | Escolher alternativa ou autorizar transcode | Política de reprodução |
| StalledPlayback | Buffering excessivo / rede | Repetir ou diagnóstico | Posição conhecida |
| UnexpectedFailure | Código de erro recuperável e destino válido | Repetir / Voltar | Navegação segura |

Nunca encerrar ou reiniciar a aplicação como única resposta a um erro de media. Nunca mostrar resultados de outra conta durante uma mudança de perfil.

---

## 8. Contratos visuais para G1 (Figma)

### 8.1 Componentes mínimos

`AppShell`, `TVNavigation`, `CinematicHero`, `MediaCard`, `MediaRow`, `PosterGrid`, `FilterChip`, `FilterPanel`, `EpisodeRow`, `SeasonPicker`, `RecommendationPrimary`, `RecommendationAlternative`, `PlayerOverlay`, `Timeline`, `TrackPicker`, `ServerConnect`, `ProfileCard`, `EmptyState`, `ErrorState`, `FocusIndicator`, `Toast`.

### 8.2 Variantes obrigatórias

Default, focused, pressed, disabled, selected, loading e error, conforme a natureza do componente. O componente MediaCard inclui `unseen`, `inProgress`, `watched`, `unavailable`, `noArtwork`. Player inclui `directPlayConfirmed`, `remux`, `audioConverted`, `videoTranscodeAuthorized`, `mediaError`.

### 8.3 Regras de interface

- Referência TV em 1920×1080; validar escala 1280×720 e densidades maiores.
- Áreas seguras e tipografia testadas à distância; evitar conteúdo colado aos limites.
- Foco sempre inequívoco mesmo em imagens brilhantes ou escuras.
- Hero não deve empurrar «A seguir» para fora do primeiro percurso acessível.
- Sem trailers automáticos com som.
- Sem modais encadeados para tarefas frequentes.
- Em transições assíncronas, não roubar foco por chegada de dados.
- Mobile reutiliza modelos de dados e linguagem, não a grelha e a navegação do comando.

---

## 9. Quality gates, evidências e critérios de aprovação

### G0 — Especificação

**Artefactos documentados neste ficheiro** (8): 1) decisões/scope; 2) mapa de rotas; 3) contrato dos 15 ecrãs; 4) contrato D-pad; 5) 12 jornadas; 6) regras de Discovery; 7) contrato de dados; 8) estados e plano de testes.

**Estado:** documentação v1.0 preparada = 8/8; validação cruzada em protótipo = 0/8. G0 não está aprovado como «testado».

### G1 — Design system + protótipo de TV

Criar os 15 ecrãs-base e overlays, pelo menos 5 cenários de UI por fluxo crítico (normal, loading, vazio, erro, regresso), um protótipo com percurso completo por D-pad e auditoria de foco. Cada ecrã precisa de destino e ação reais, sem botões decorativos.

### G2 — Prova Jellyfin/TrueNAS

Ambiente reproduzível; autenticação sem administrador na TV; contratos de API validados; capacidade de escolher player e perfil de codecs; observação real de Direct Play. Matriz de testes H.264 1080p, HEVC 4K HDR, MKV/MP4, AAC/EAC3, legendas SRT/PGS e falhas. Três 4K em paralelo em Direct Play, com CPU, GPU, I/O, rede e buffering observados.

### G3 — Cliente TV utilizável

Home, navegação, filmes, séries, pesquisa, detalhes, player, progresso, idioma, erro e perfil totalmente funcionais num dispositivo real; sem transcodificação de vídeo oculta; saída do player restaura contexto.

### G4 — Discovery completo

Filtros obrigatórios respeitados, 1+2 propostas, diversidade, sem repetições dentro da sessão quando há candidatos, explicações fiáveis, estados com 0/1/2 títulos e alteração manual de filtros.

### G5 — Ecossistema

Mobile/web e outros sistemas com players adequados, continuidade verificada e testes de acessibilidade/plataforma.

---

## 10. Testes de aceitação essenciais (a executar)

| ID | Teste | Prova esperada |
|---|---|---|
| AT-01 | Primeiro arranque LAN | Associação sem credenciais escritas com comando quando Quick Connect disponível |
| AT-02 | Reabertura TV | Sessão válida reutilizada |
| AT-03 | Pesquisa e regresso | Termo e cartão focado preservados |
| AT-04 | Filtro sem candidatos | Não relaxar filtros silenciosamente |
| AT-05 | Descoberta até 120min | 100% dos resultados elegíveis ≤120 min, com duração conhecida |
| AT-06 | Só não vistos | 0 resultados marcados como vistos/em progresso |
| AT-07 | Trio 1+2 | Alternativa promovida sem reprodução e sem perder histórico do trio |
| AT-08 | Episódio seguinte | Ordem correta; especiais e episódios ausentes não induzem salto silencioso |
| AT-09 | D-pad | Todos os controlos acessíveis; foco sempre visível |
| AT-10 | Player e voltar | Salto/seek/legendas previsíveis; regresso à origem |
| AT-11 | Sessão/Jellyfin indisponível | Mensagem e retry; não pedir login só porque NAS reiniciou |
| AT-12 | Contas distintas | Não partilhar progresso ou cache privado |
| AT-13 | Modo de reprodução | Direct Play observado na atividade Jellyfin |
| AT-14 | Vídeo incompatível | Não transcodificar vídeo sem autorização do perfil e do utilizador |
| AT-15 | 3×4K em simultâneo | Três Direct Play observados; métricas de CPU/GPU/rede recolhidas |
| AT-16 | Mudança de versão Jellyfin | Cliente mantém fluxos ou bloqueia atualização incompatível de forma segura |

**Critério de fecho:** evidências (capturas do protótipo, registos de navegação, ficheiros de teste e medições) por teste, com resultado PASS/FAIL/BLOCKED. Não considerar desenho «concluído» se o fluxo não regressa a um ponto previsível.

---

## 11. Dependências ainda não confirmadas

1. **Modelo exato da primeira TV** e sistema operativo: determina o player e a matriz real de codec/HDR/áudio.
2. **Instalação real do Jellyfin** e versão exata: determina a integração OpenAPI e Quick Connect.
3. **Organização dos datasets e partilhas TrueNAS**, rede e formatos predominantes: determina o plano de testes e a montagem de ficheiros.
4. **Política de autenticação multiutilizador** na TV familiar: testar armazenamento seguro e remoção/revogação de sessões.
5. **Performance medida em simultâneo** no i5-14600: prevista como confortável em Direct Play, mas não afirmada como validada.

Estas incógnitas **não bloqueiam o design system nem os wireflows**; serão critérios obrigatórios no G2.

---

## 12. Progresso honesto

| Indicador | Estado em 11-10-2026 |
|---|---|
| G0 artefactos escritos | **8/8 = 100% da baseline documental v1.0** |
| G0 artefactos aprovados em protótipo | **0/8** |
| Ecrãs TV finais no Figma | **0/15 verificados** |
| Testes técnicos executados | **0/16** |
| Apps instaláveis | **0** |
| Implementação validada | **0%** |

**Próximo trabalho:** G1: construir o design system e 15 ecrãs, começando por Home → Discovery → Ficha → Player e em paralelo G2: prova Jellyfin + player no dispositivo real.

---

## 13. Fontes técnicas consultadas

- Jellyfin, Transcoding: https://jellyfin.org/docs/general/post-install/transcoding/
- Jellyfin, Codec Support: https://jellyfin.org/docs/general/clients/codec-support/
- Jellyfin, Quick Connect: https://jellyfin.org/docs/general/server/quick-connect/
- Jellyfin, Users: https://jellyfin.org/docs/general/server/users/
- Jellyfin, 12.0 release (07-09-2026): https://jellyfin.org/posts/jellyfin-release-12.0/
- Android TV, Navigation on TV: https://developer.android.com/design/ui/tv/guides/foundations/navigation-on-tv
- Android TV, Focus system: https://developer.android.com/design/ui/tv/guides/styles/focus-system

*Esta especificação é um artefacto de planeamento, não uma comprovação de funcionamento no hardware final.*
