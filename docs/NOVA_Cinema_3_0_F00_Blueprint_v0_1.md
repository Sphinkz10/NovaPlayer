# NOVA Cinema 3.0 — F00 · Blueprint funcional

**Versão:** 0.1 · **Data:** 12-10-2026  
**Estado:** Especificação-base redigida; **revisão/aceitação do proprietário pendente**.  
**Âmbito:** desenho funcional e roadmap; não é aplicação implementada.  
**Figma — Product Blueprint (7 slides editáveis):** https://www.figma.com/design/AAwpusB10YU5tXg4y8Z6P3?node-id=109-2  
**Figma — Template Signature 1080p:** https://www.figma.com/design/AAwpusB10YU5tXg4y8Z6P3?node-id=69-2  
**Figma — Template Signature 720p:** https://www.figma.com/design/AAwpusB10YU5tXg4y8Z6P3?node-id=80-2

> **Integridade do progresso:** Os 50 ecrãs/estados Signature e as 370 ligações são resultados previamente validados no protótipo Figma. Não significam implementação das funcionalidades NOVA 3.0. F00 define requisitos; Kotlin, backend, NAS, serviços externos e testes reais permanecem por iniciar.

## 1. Visão e compromissos

A NOVA é um cinema privado, doméstico e familiar, usado principalmente em Android TV e na **Xiaomi TV Box S de 2.ª geração**, com acesso remoto autorizado. Une três domínios distintos:

- **Ver:** conteúdos realmente existentes no Jellyfin e autorizados ao perfil, com Direct Play preferencial.
- **Descobrir:** estreias, anúncios, capas, fichas e trailers, mesmo quando o conteúdo ainda não existe no NAS.
- **Planear:** watchlist ordenável, pedidos, preferências, calendário e sessões com data/hora opcionais.

**Princípios inegociáveis**

1. Um título não precisa de existir no NAS para aparecer no catálogo NOVA.
2. «Seguir», «Pedir», «Adicionar à fila» e «Agendar» são ações independentes. Nenhuma desencadeia outra sem confirmação explícita.
3. «▶ Reproduzir» só aparece/funciona se o utilizador puder aceder ao item e existir uma fonte real reproduzível. O NAS offline não deve ser confundido com indisponibilidade de catálogo.
4. A NAS e a administração TrueNAS não são publicadas para familiares; o acesso remoto será privado, encriptado e restringido ao serviço de media autorizado. A escolha concreta de UniFi/VPN é **adiada**.
5. A NOVA não obtém conteúdos de fontes não autorizadas. Pedidos são propostas ao administrador, não downloads automáticos.
6. A watchlist, o histórico, as sugestões e os calendários são privados por defeito; partilha só com destinatários escolhidos.
7. O sistema é modular, com dados próprios separados dos dados e ficheiros do Jellyfin. Alterações de tema/layout não exigem reescrever a lógica da aplicação.
8. Smart é primeiro **regras explicáveis**; aprendizagem adicional e envio de dados a terceiros são opcionais, com consentimento.

## 2. Navegação aprovada como **proposta-base**, não decisão final

**Barra principal TV:** `Início · Biblioteca · Descobrir · Estreias · Planner`.  
**Cabeçalho:** pesquisa global, notificações e perfil.  
**Biblioteca:** Filmes, Séries, Anime, Coleções; favoritos/continuar a ver na Home.  
**Descobrir:** «O que vamos ver?» com sugestão principal + 2 alternativas; duração inicial até 120 min; «Surpreende-me» e não vistos. O conjunto é reproduzível por defeito.  
**Estreias:** trailers, lançamentos regionais e anunciados (cinema/séries/anime), com seguir/solicitar/guardar.  
**Planner:** fila ordenável, por programar, calendário, sessões partilhadas.

Não colocar as administrações do NAS na navegação da TV. O futuro **NOVA Control** será uma área administrativa isolada.

## 3. Fontes de informação e identidade

| Domínio | Fonte preferida | Regra |
|---|---|---|
| Ficheiros, disponibilidade, autorização, histórico de visualização | Jellyfin | Autoridade para reproduzir e consultar bibliotecas privadas |
| Informações de filmes/séries, cartazes e datas regionais | TMDB (sujeito a condições de API, atribuição e licenças) | Apenas enriquecimento e catálogo externo; não prova que exista ficheiro |
| Trailers oficiais | Referência autorizada ao player/plataforma de origem, por exemplo YouTube | Não descarregar trailers indevidamente; verificar tipo, região e player em Android TV |
| Anime | Metadados compatíveis e fontes autorizadas; AniList a avaliar | Condições comerciais e de rastreio têm de ser revistas antes da integração |
| Watchlist, interesses, sessões, pedidos, convites, notificações | Backend NOVA | Não depender do Jellyfin para dados de planeamento |

**Identificação canónica:** um `catalog_item_id` interno imutável, mapeado para os identificadores externos relevantes, e zero ou mais `jellyfin_item_id` associados. Séries/temporadas/episódios são entidades diferentes, com associação explícita e correspondência cuidadosamente validada. Não fundir conteúdos diferentes só por coincidência de título.

## 4. Dois diretórios de ficheiros

A primeira versão tem de aceitar pelo menos **dois caminhos de origem** (`source_A`, `source_B`) e suportar crescimento. O Jellyfin agrega várias pastas em bibliotecas ou expõe bibliotecas separadas que a NOVA apresenta de forma unificada. Ler de ambos não implica que a NOVA tenha direitos de escrita/apagar ficheiros.

**Regras funcionais:**

- A origem física não aparece como etapa obrigatória de navegação ao familiar.
- Cada origem tem estado próprio de saúde (online/offline, última análise), sem apagar informações já guardadas quando fica temporariamente inacessível.
- Reconciliação por IDs e assinaturas de metadados, com revisão administrativa para correspondências ambíguas.
- O mesmo filme em duas qualidades é apresentado preferencialmente como um título com opções de media, sujeitos às permissões; episódios diferentes não são duplicados.
- Uma nova pasta/ficheiro desencadeia análise e atualização incremental ou periódica de segurança, com deduplicação de eventos.

**Pendente:** confirmar se as duas pastas estão no mesmo TrueNAS ou em equipamentos diferentes; não é bloqueador para fechar F00.

## 5. Modelo de estados: não confundir dimensões

Em vez de um único campo `status`, modelar pelo menos:

- **Publicação externa:** anunciado, lançamento futuro, já estreado, sem data confiável.
- **Disponibilidade física:** sem correspondência no Jellyfin; ficheiro disponível; fonte offline; media retirado; correspondência incerta.
- **Acesso por perfil:** autorizado, não autorizado, conta suspensa/sessão expirada.
- **Interesse:** não seguido, seguido; prioridade manual de watchlist.
- **Pedido:** inexistente, submetido, em revisão, aprovado, adiado, rejeitado, satisfeito.
- **Sessão:** não agendada, rascunho/sem data, proposta, confirmada, adiada, cancelada, realizada; disponibilidade verificada separadamente.
- **Consumo:** por ver, em progresso, visto — proveniente ou sincronizado com Jellyfin por identidade/perfil.

**Invariante de reprodução:** `can_play = identity_ok && access_allowed && playable_media_present && authorized_stream_path`. Offline mostra «Voltar a tentar» e não declara falsamente que o filme desapareceu. Um título pedido pode continuar por estrear ou já ter estreado; as situações não são mutuamente exclusivas.

## 6. Jornadas de utilizador

### J01 · Entrada e descoberta

1. Abrir a NOVA, recuperar sessão autenticada ou solicitar autenticação.
2. Selecionar perfil autorizado e carregar a Home com progresso pessoal.
3. Mostrar «Continuar», «Adicionados recentemente», «O que vamos ver?» e próximas sessões.
4. Em falha de ligação, conservar estrutura e mostrar cache identificada como offline, com caminho para reconexão; não disponibilizar reprodução inexistente.

### J02 · Reproduzir disponível

1. Abrir um filme existente na biblioteca autorizada.
2. Mostrar poster/fundo, sinopse, duração, contexto e estado de reprodução.
3. «Reproduzir» abre o player correcto; priorizar Direct Play.
4. Oferecer faixas de áudio/legendas disponíveis e retomar progresso.
5. Se formato/rede não suportados, explicar incompatibilidade, propor fonte alternativa e pedir confirmação antes de qualquer conversão de vídeo.

### J03 · Estreia → pedido → chegada

1. Localizar título externo com data/região/fornecedor e trailer oficial verificado.
2. `Seguir`: guardar interesse, sem pedido nem agendamento automático.
3. `Pedir`: enviar pedido único por título, agregando interessados sem revelar indevidamente as respetivas identidades.
4. Administrador analisa e altera estado, sem download implícito.
5. Quando um ficheiro legalmente adicionado ao Jellyfin for associado por ID, marcar como disponível **só para perfis autorizados**.
6. Notificar uma única vez quem optou por receber avisos; preservar fila e sessões.

### J04 · Fila → calendário

1. Colocar o título na watchlist; prioridade e posição manuais.
2. Mover para cima/baixo via D-pad; futura aplicação mobile/web poderá usar arrastar.
3. Opcionalmente escolher data; hora e convidados também opcionais.
4. A sessão guarda timezone explícito e dura uma estimativa modificável (filme ou conjunto de episódios).
5. Antes da sessão, verificar disponibilidade para participantes autorizados; se faltar um ficheiro, avisar e oferecer alternativa ou reagendamento **sem alterar automaticamente** o plano.

### J05 · Episódio novo

1. Detetar novo episódio numa das origens; confirmar identificação de série, temporada e episódio.
2. Atualizar catálogo sem duplicação de avisos.
3. Para quem acompanha a série e tem permissão, mostrar «Novo episódio» e próximo por ver.
4. Evitar revelar spoilers/metadados de episódios futuros quando as preferências assim o exigirem.

### J06 · Acesso remoto familiar

1. Dispositivo autorizado conecta-se por acesso privado, sujeito a regras restritivas.
2. Conta Jellyfin individual para histórico e acesso aos media; associação ao perfil NOVA sem atribuir poderes de administração.
3. Reproduzir com avaliação de bitrate e capacidade, mantendo o controlo explícito de transcodificação.
4. Em dispositivo perdido, administrador revoga acesso e tokens/sessões; testar ausência de acesso ao TrueNAS/SMB/SSH/LAN.

## 7. Matriz de permissões (proposta)

| Ação | Proprietário / admin NOVA | Familiar | Convidado a sessão |
|---|---:|---:|---:|
| Ver apenas conteúdos do Jellyfin permitidos à sua conta | Sim | Sim | Só se tiver conta autorizada |
| Ver estreias/trailers públicos da NOVA | Sim | Sim | Conforme convite/conta |
| Gerir a própria fila e calendário | Sim | Sim | Apenas a sua participação |
| Pedir conteúdo | Sim | Sim | Não por defeito |
| Aprovar pedidos e gerir fontes | Sim | Não | Não |
| Gerir contas e regras de media | Admin autorizado | Não | Não |
| Aceder a TrueNAS, SSH, SMB, rede doméstica | Exclusivamente por canal administrativo separado | Não | Não |

Um perfil nunca pode ampliar os privilégios da conta Jellyfin associada. **Negar por defeito.** Registar auditoria de ações administrativas sem recolher dados pessoais desnecessários.

## 8. Motor Smart V1 — regras transparentes

**Smart Pick 1+2:** filtrar primeiro pelo acesso real e disponibilidade do item; segundo por estado (não visto/retomar), duração inicial ≤120 minutos e escolha do utilizador. Ordenar por afinidade de géneros, idioma/legendas, novidade, diversidade e adequação ao tempo. Evitar recomendação duplicada nas três opções. Mostrar «Por que foi sugerido?». Se nenhuma opção satisfizer os filtros, oferecer escolha explícita de relaxar duração ou estado de visto — não mudar em silêncio.

**Smart Queue:** sugerir uma possível ordem, mas a fila manual tem precedência; não reordenar autonomamente. **Smart Premieres:** permitir seguir séries, datas e avisos segmentados por região. **Smart Session:** apresentar duração prevista e disponibilidade; não confirmar nem reagendar sem ação do utilizador. **Smart Privacy:** desativar personalização, limpar preferências locais e manter histórico privado.

**V1 sem IA obrigatória:** os resultados devem ser reproduzíveis e testáveis com fixtures; eventuais modelos adicionais terão contrato isolado e política explícita de privacidade.

## 9. Design e comportamento TV

**Alvo inicial:** Xiaomi TV Box S de 2.ª geração, Android TV/Google TV e outras TVs compatíveis. **Design existente:** Template 01 Original preservado; Template 02 Signature com 25 ecrãs/estados 1080p e 25 720p, documentação e componentes partilhados. Estes ecrãs ainda **não** cobrem visualmente o produto 3.0 inteiro.

- D-pad: todas as direções têm percurso previsível ou explicação; destacar foco; Back recupera estado anterior.
- Overlays: Pesquisa, filtros, áudio/legendas, pedidos, sessão, confirmação, erro/offline.
- Legibilidade: mínimo estrutural 18 px usado na auditoria de 720p, sujeito a validação real pela distância de visionamento.
- Performance: imagens dimensionadas e cache, pré-carregamento limitado, sem blur dinâmico caro; validar em hardware real.
- Conteúdo de demonstração não pode ser confundido com disponibilidade verdadeira.
- Navegação TV principal em cinco áreas; telemóvel/web futuro para organizar grandes filas e calendários.

## 10. Segurança e rede — opções adiadas, princípios fechados

**Requisito:** familiares veem media autorizado sem alcance administrativo ao NAS. A UDR Wi-Fi 6 permite desenhar políticas de rede segmentadas, mas **a configuração específica fica adiada** por decisão do proprietário. Não abrir portas de TrueNAS ou Jellyfin sem uma revisão explícita. Acesso remoto deve ser autenticado, revogável e restrito. Antes de aprovar acesso familiar, testar uma conta/dispositivo de convidado e demonstrar que TrueNAS/SMB/SSH não estão acessíveis.

**Capacidade:** 500 Mbps de upload nominal, sem inferir desempenho VPN ou streams 4K reais. A prioridade é Direct Play; remux/transcode áudio segundo compatibilidade; transcodificação de vídeo permanece desativada por defeito até consentimento. Medir caminho direto/relay, picos de bitrate, múltiplos streams e qualidade nas TVs.

## 11. Requisitos funcionais identificados (rastreáveis)

| ID | Requisito | Prioridade | Condição de aceitação futura |
|---|---|---|---|
| R-001 | Duas origens de ficheiros | P0 | Filmes de A e B aparecem sem navegar por pastas |
| R-002 | Contas independentes | P0 | Histórico A nunca aparece para B |
| R-003 | Aplicação TV com D-pad | P0 | Todas as ações essenciais operáveis com comando |
| R-004 | Disponibilidade por perfil | P0 | Proibido não pode reproduzir nem obter dados privados |
| R-005 | Jellyfin/Direct Play | P0 | Testes G2 passam na Xiaomi |
| R-006 | Novas entradas/episódios | P0 | Sincronização incremental sem duplicações |
| R-007 | Capas/cache/fallbacks | P0 | UI estável com ou sem artwork e offline |
| R-008 | Acesso remoto familiar | P0 | Media funciona sem acesso a administração NAS |
| R-009 | Sugestões 1+2 | P0 | Três opções distintas ou fallback explicitado |
| R-010 | Trailers oficiais | P1 | Player autorizado abre trailer do título correcto |
| R-011 | Estreias cinema/séries/anime | P1 | Região, data e fonte visíveis |
| R-012 | Seguir estreias | P1 | Não gera pedido nem agendamento |
| R-013 | Pedidos aprováveis | P1 | Duplicados agregados, auditáveis |
| R-014 | Watchlist ordenável | P1 | Reordenar por D-pad sem perder estado |
| R-015 | Calendário opcional | P1 | Título pode continuar sem data |
| R-016 | Convidados e partilha | P1 | Apenas convidados veem sessão partilhada |
| R-017 | Smart explicável | P1 | Motivo claro e personalização opcional |
| R-018 | Diagnóstico remoto | P0 | Identificar falha rede vs ficheiro vs codec |
| R-019 | Revogação de acesso | P0 | Dispositivo revogado deixa de conseguir chegar ao serviço |
| R-020 | Backup de configuração | P0 | Restaurar configs e DB NOVA num ensaio documentado |

## 12. Critérios de aceitação a executar (não testados)

- **AC-01** Perfil sem acesso a biblioteca privada não pode localizar ou reproduzir o respetivo media por endpoints alternativos.
- **AC-02** Título externo anunciado mostra trailer/seguir/pedir; não mostra botão Reproduzir.
- **AC-03** «Seguir» não cria pedido nem sessão.
- **AC-04** Dois pedidos iguais são agregados, preservando interessados sem duplicar registos visíveis ao administrador.
- **AC-05** Um ficheiro em cada diretório aparece corretamente; remover temporariamente uma origem não elimina watchlist.
- **AC-06** Várias qualidades do mesmo título são conciliadas corretamente e não confundidas com duas obras diferentes.
- **AC-07** Ficheiro que chega e corresponde a título seguido permite aviso único após autorização e confirmação de disponibilidade.
- **AC-08** Próximo episódio reflete progresso individual e não mistura temporadas/perfis.
- **AC-09** A fila pode ser reordenada por controlo remoto e guardar ordem após reinício.
- **AC-10** Uma sessão pode ser criada sem data/hora; convidados não recebem dados até convite explícito.
- **AC-11** Sessão marcada para conteúdo indisponível sinaliza risco, propõe alternativas e não muda automaticamente.
- **AC-12** Convidado remoto consegue apenas aceder ao serviço autorizado; testes negativos à administração NAS, SSH, SMB e outras VLANs.
- **AC-13** Dispositivo revogado perde acesso, incluindo sessões existentes dentro da política de expiração.
- **AC-14** Rede lenta ou codec incompatível apresenta diagnóstico; vídeo não é convertido silenciosamente.
- **AC-15** NAS offline preserva listas e permite novo teste, sem apresentar conteúdos como apagados.
- **AC-16** Recomendações mostram justificação, respeitam filtro até 120 min por defeito e não expõem histórico alheio.
- **AC-17** Todas as ações essenciais funcionam por D-pad, incluindo fechar filtros, Back, mover títulos e confirmar sessões.
- **AC-18** Acesso remoto simultâneo, desempenho de imagem e 8 testes G2 verificados no hardware real.

## 13. Roadmap de execução e gates

| Marco | Entregável observável | Gate |
|---|---|---|
| F00 — Produto 3.0 | Esta especificação + slides/fluxos + requisitos e exceções | Proprietário revê e aceita/adapta decisões |
| F01 — Arquitetura | Modelo de dados, APIs, isolamento de módulos, plano de testes | Contratos e permissões revistos |
| F02 — Bibliotecas | Duas origens no Jellyfin, metadados, ficheiros e duplicados | Biblioteca testada com ambos os caminhos |
| F03 — APK básica | TV app abre, autentica, lista, pesquisa com D-pad | APK na Xiaomi |
| F04 — Player | Media3, Direct Play, áudio/legendas e progresso | 8 provas G2 documentadas |
| F05 — Remoto | Acesso privado, gateway e várias contas | Testes negativos de rede e streams reais |
| F06 — Sincronização | Imagens, cache, novos media e IDs externos | Deteção sem duplicações |
| F07 — Estreias | Trailers, catálogos regionais, seguir | Estreias externas sem falso ▶ |
| F08 — Pedidos | Pedido, aprovação e chegada | Ciclo completo com interessados |
| F09 — Planner | Fila, calendário, convites | Jornada de sessão testada |
| F10 — Smart | Regras 1+2, filas, avisos e privacidade | Fixtures e feedback dos perfis |
| F11 — Final | Qualidade, segurança, acessibilidade, estabilidade | Versão de lançamento testada |

**Sequência de entrega:** A (TV local reproduz) → B (família remota segura) → C (Smart/Estreias/Planner) → D (release validada). A ordem fina e a abrangência mínima da primeira APK devem ser decididas em F01, sem criar uma V1 que já exija toda a inteligência avançada.

## 14. Estado F00 por entregável (sem percentagens fictícias)

| Entregável F00 | Estado | Evidência |
|---|---|---|
| Visão/arquitetura funcional conceptual | Rascunho pronto | Secções 1–3 |
| Navegação e jornadas principais | Rascunho pronto | Secções 2 e 6 + Figma F00-01/02/06/07 |
| Modelo de estados e permissões | Rascunho pronto | Secções 5 e 7 + Figma F00-03/04 |
| Smart e políticas essenciais | Rascunho pronto | Secções 8–10 + Figma F00-05 |
| Critérios de aceitação e backlog | Rascunho pronto | Secções 11–13 |
| Revisão/aprovação do proprietário | **Pendente** | Sem validação nesta conversa |

**Indicador administrativo F00:** 5/6 entregáveis **redigidos ou desenhados**, 0/1 aprovados pelo proprietário; **não** equivale a 83% de produto implementado. Android TV funcional = **0%**, testes físicos G2 = **0/8**.

## 15. Decisões ainda abertas para o proprietário

1. Os dois diretórios estão fisicamente no mesmo NAS? (Necessário antes de F02; não bloqueia F00.)
2. Queremos que familiares possam pedir títulos livremente ou haverá limites por conta? (Default: livre com deduplicação, aprovação humana.)
3. As sessões partilhadas apenas marcam encontro ou incluirão mais tarde reprodução sincronizada? (Default: apenas planeamento.)
4. Devemos disponibilizar apenas Android TV na primeira APK ou também priorizar web/mobile para o Planner? (Default: Android TV primeiro.)
5. Que filtros de estreias regionais são mais relevantes — Portugal por defeito? (Default: Portugal, configurável por perfil.)
6. Política final de acesso remoto no UniFi/VPN fica para o gate F05, conforme pedido do proprietário.

**Próximo passo recomendado:** revisão F00 orientada por decisões: manter ou alterar a navegação proposta, confirmar a política de perfis/pedidos e fixar o âmbito mínimo da primeira APK. Depois executar F01 com um backlog técnico decomponível e testes concretos.


## 16. Cobertura do Figma e recuperação sem becos sem saída

**Figma F00-06 · Cobertura UX:** https://www.figma.com/design/AAwpusB10YU5tXg4y8Z6P3?node-id=110-2  
**Figma F00-07 · Recuperação:** https://www.figma.com/design/AAwpusB10YU5tXg4y8Z6P3?node-id=110-39

### Ecrãs existentes que se reaproveitam (desenho inicial, não implementação)

Home, Biblioteca, Descobrir 1+2, pesquisa/filtros, fichas, player, Minha Lista, perfis, definição e offline. O redesign de estados e novas entradas terá de preservar os percursos aprovados.

### Ecrãs novos exigidos pela visão 3.0 (todos por desenhar/validar)

1. Estreias (cinema / séries / anime com filtros regionais).
2. Ficha de obra anunciada ou indisponível, sem falso botão de reprodução.
3. Modal/fluxo de Seguir, Pedido e acompanhamento de pedido.
4. Fila com prioridade e movimento por D-pad.
5. Calendário, detalhe de sessão, data/hora opcionais e confirmação.
6. Convites/participantes de sessão e respetiva privacidade.
7. Centro de notificações e regras de preferência.
8. NOVA Control administrativo em superfície separada da TV.

### Obrigações de recuperação por condição

| Falha ou caso-limite | Resposta da NOVA | Saída útil |
|---|---|---|
| NAS offline | Mostrar cache identificada como offline | Voltar a tentar, diagnóstico, Back |
| Sem resultados | Preservar consulta e critérios | Limpar filtros, mudar pesquisa |
| Trailer não encontrado | Não mostrar player fictício | Seguir, ver ficha, Back |
| Sem permissão para media | Não divulgar ficheiros/IDs privados | Trocar perfil, Back |
| Pedido duplicado | Mostrar pedido e seu estado | Acompanhar/retirar interesse |
| Sessão cujo filme está indisponível | Assinalar «pendente de media» | Reagendar, sugerir outro título |
| Formato ou rede insuficiente | Explicar codec, faixa e ligação | Escolher opção suportada ou voltar |
| Sem consentimento para notificações | Não subscrever nem enviar avisos | Reativar manualmente nas definições |

**Nova regra de gate F00:** antes de declarar um percurso fechado, identificar entrada, ação principal, sucesso, erro/sem dados, permissões, recuperação e comportamento da tecla Back. Este levantamento funcional não valida ainda o comportamento físico do comando.
