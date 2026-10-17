# NOVA Cinema 3.0 — F01 · Arquitetura modular

**Versão:** 0.1 · **Data:** 12-10-2026  
**Estado:** desenho técnico proposto; **F00 aguarda aceitação do proprietário**.  
**Importante:** nenhuma alteração feita à UDR, ao TrueNAS, Jellyfin ou a qualquer repositório; APK não implementada.  
**Âmbito:** execução do planeamento F01, sem antecipar configuração de rede ou código de produção.

## 0. Contexto e decisões herdadas

- Cinema pessoal/privado para proprietário e familiares convidados. Dispositivo inicial: Xiaomi TV Box S de 2.ª geração; ecrãs TV Signature 1080p e 720p existem no Figma.
- Media proveniente de **pelo menos dois diretórios** no TrueNAS/Jellyfin. O caminho físico não faz parte da navegação do utilizador.
- A aplicação deve funcionar em casa e futuramente fora de casa, sem permitir acesso ao painel do NAS, SMB, SSH ou à restante LAN.
- Jellyfin é **autoridade da disponibilidade de media, permissão de biblioteca, estado de playback**; o catálogo NOVA não concede por si só permissão de reprodução.
- TMDB ou fonte autorizada cobre títulos, estreias, cartazes e trailers ainda não disponíveis na biblioteca; só correspondências verificadas autorizam associação a ficheiros.
- NOVA gere **follow, pedido, watchlist, ordem, sessões, convites, notificações e sugestões** independentemente do Jellyfin.
- O Smart começa como motor determinístico e explicável, sem transferir históricos para terceiros por defeito.
- Direct Play é prioridade; conversão de vídeo é desativada por defeito e depende de consentimento/política definida para o servidor.
- **F00 ainda não está formalmente aprovado.** Este documento é um desenho reversível para facilitar essa revisão, não decisão sobre todas as opções de stack.

## 1. Arquitetura lógica proposta

```text
Android TV: Compose for TV / D-pad / media artwork / Media3 (ExoPlayer)
      | HTTPS via ligação PRIVADA (estratégia de VPN adiada)
      v
NOVA API / Session boundary (autenticação, autorização, limites, auditoria)
      |-- Catalog module             [títulos canónicos, provider refs, variantes]
      |-- Library Sync module        [2+ sources, reconciliação, deteção, cursor]
      |-- Discovery module           [estreias, trailers, país/idioma, cache externa]
      |-- Requests module            [pedidos, interesses, aprovação, deduplicação]
      |-- Planner module             [fila ordenável, sessões, convites, timezone]
      |-- Smart module               [regras e recomendações explicáveis]
      |-- Notification module        [outbox, dedup, opt-in, privacidade]
      |-- Health/Admin module        [diagnóstico, logs mínimos e configuração]
      |
      +--> PostgreSQL (NOVA data + transactional outbox + sync state)
      +--> Jellyfin Adapter (APIs de utilizador e inventário sem ignorar permissões)
      |            +--> Jellyfin --> montagem READ ONLY diretório A e B
      +--> Metadata Adapter (TMDB ou fornecedores autorizados; caches e quotas)
      +--> Trailer provider adapter (abrir player oficial, não ripar media)
```

**Padrão de implementação:** monólito modular para V1, com módulos e contratos separados; evitar iniciar 8 microsserviços para uma utilização familiar. Um `worker` separado para jobs assíncronos e uma BD partilhada é suficiente no arranque. Redis/message broker são opcionais, adicionados apenas por necessidade medida.

**Stack de trabalho — PROPOSTA, ainda por aprovar:** App TV Kotlin + Jetpack Compose for TV + Media3/ExoPlayer; serviço API Python/FastAPI ou Kotlin/Ktor; PostgreSQL com migrações versionadas; job scheduler/outbox; container isolado no TrueNAS ou host separado; UI de administração React quando for necessária. Os contratos deverão ser independentes da linguagem do backend.

**Dependência importante:** se autenticação direta no Jellyfin for usada, as credenciais/token de media do utilizador devem ficar protegidas. O backend não deve passar aos clientes um token global de administração. O fluxo de streaming deve ser validado contra as permissões reais do perfil e as capacidades do dispositivo.

## 2. Limites de confiança e papel de cada sistema

| Sistema | Responsabilidade | Não deve fazer |
|---|---|---|
| TrueNAS | Armazenamento, snapshots, volumes, administração por proprietário | Aceitar administração de familiares |
| Jellyfin | Indexação, playback/estado, conteúdos e permissões | Ser base de dados de pedidos/agenda NOVA |
| NOVA API | Identidade de produto, catálogo, regras e autorizações por ação | Tratar estar na VPN como autorização suficiente |
| NOVA Database | Interesses, filas, pedidos, convites e auditoria mínima | Copiar ficheiros de vídeo ou credenciais em claro |
| TMDB/externos | Informação pública, trailers e cartazes sujeitos a condições | Conferir disponibilidade local de reprodução |
| App Android TV | UI, D-pad, player de media, armazenamento local mínimo | Guardar chave de administração Jellyfin |
| NOVA Gateway | Encaminhar só endpoints autorizados da app | Expor a LAN, painel TrueNAS, SMB ou SSH |

Acesso remoto: não configurar a UDR nesta fase. O futuro gate NET exige conectividade a serviço específico, **negação por defeito** nas regras de acesso, prova negativa contra SMB/SSH/painéis e capacidade de revogar dispositivos. A lista de clientes da VPN nunca deve atribuir implicitamente permissão para media. Além da rede privada, verificar ACLs/roles no backend.

## 3. Modelo de dados canónico — esquema v0.1

| Tabela / agregado | Campos centrais | Invariantes importantes |
|---|---|---|
| `catalog_item` | `id UUID`, `type movie/series/season/episode`, `parent_id`, `title`, `year`, `canonical_status` | Identificador NOVA imutável; `canonical_status` não confunde disponibilidade Jellyfin |
| `provider_ref` | `catalog_id`, `provider`, `kind`, `provider_item_id`, `confidence`, `verified_at` | Unicidade `(provider,kind,provider_item_id)`; conflitos passam a revisão |
| `media_origin` | `id`, `source_key`, `library_id`, `mount_ref`, `health`, `last_scan` | 2+ origens; guardar `mount_ref` no servidor, nunca devolver path aos familiares |
| `media_asset` | `id`, `jellyfin_server_id`, `jellyfin_item_id`, `origin_id`, `catalog_id`, `edition`, `codecs`, `bitrate`, `health` | Zero ou várias versões; não devolver `jellyfin_item_id` privado sem autorização |
| `catalog_match` | `candidate_id`, `catalog_id`, `match_method`, `score`, `decision`, `reviewed_by` | Correspondência duvidosa não fica disponível automaticamente |
| `nova_account` | `id`, `role owner/family`, `state`, `created_at` | Cada pessoa é identidade isolada; admin NAS nunca é propagado |
| `jellyfin_identity` | `nova_account_id`, `jellyfin_user_id`, `token_ref`, `link_status` | Ligação 1:1 inicial, token protegido; verificar permissões Jellyfin sempre |
| `follow` | `account_id`, `catalog_id`, `type premiere/series`, `notifications` | Não cria pedido/watchlist/sessão por efeito lateral |
| `content_request` | `id`, `catalog_id`, `state`, `created_by`, `updated_at` | Um processo por título ativo; não implica download |
| `request_interest` | `request_id`, `account_id`, `created_at` | Uma manifestação de interesse por conta/pedido |
| `watchlist_entry` | `id`, `account_id`, `catalog_id`, `rank_key`, `created_at` | Ordem explícita por utilizador; `(account_id,catalog_id)` único |
| `watch_session` | `id`, `owner_id`, `title`, `start_at_utc nullable`, `timezone`, `duration_estimate`, `state` | Data/hora opcionais e convite independente; disponibilidade é verificada na visualização |
| `session_item` | `session_id`, `catalog_id`, `episode_range`, `position` | Suporta sessões com 1 filme ou vários episódios |
| `session_invitee` | `session_id`, `account_id`, `response`, `responded_at` | Só convidado vê sessão; sem partilha implícita da agenda |
| `notification_event` | `id`, `account_id`, `category`, `dedup_key`, `event_at`, `delivery_state` | `(account_id,dedup_key)` único; respeitar opt-in |
| `sync_cursor` | `id`, `source`, `last_scan`, `last_success`, `cursor`, `error_count` | Jobs idempotentes, retry com backoff e reconcile periódico |
| `audit_event` | `actor_id`, `action`, `resource_id`, `timestamp`, `result` | Nunca guardar tokens/URLs de streaming nos logs |

Regras de modelação:
- `catalog_item` não tem um `is_available` global. A disponibilidade é **calculada por perfil** a partir de `media_asset` + permissões Jellyfin + ligação/estado da origem.
- Estados de lançamento (anunciado/estreado) e estados de pedido/sessão/watchlist são **ortogonais**, não um enum gigante.
- Capas têm referência à origem, língua, tipo (poster/backdrop/thumb/logo), resolução disponível, tag/ETag/cache e atribuição quando exigida.
- Episódios têm `parent_id` da temporada; temporadas pertencem à série. Comparar S/E e IDs, nunca só nomes.
- Todos os valores temporais persistidos em UTC com `timezone` IANA associado quando o utilizador escolhe hora local.

## 4. Contratos de API NOVA (rascunho, não endpoints implementados)

Base versionada `/api/v1`. Autorização baseada em sessão curta e identidade de utilizador, com respostas neutras perante media privado. Todas as mutações exigem idempotency key quando o retry puder duplicar ações.

| Método | Endpoint | Responsabilidade | Segurança |
|---|---|---|---|
| GET | `/home` | Resumo por perfil: continuar, novidades, sessões | Filtrar biblioteca na origem e destino |
| GET | `/catalog?type=&status=&cursor=` | Catálogo autorizado, com vista própria de estreias | Sem revelar media privado |
| GET | `/catalog/{catalogId}` | Ficha canónica + ações permitidas calculadas | Ocultar metadados privados da biblioteca |
| GET | `/library?type=&cursor=` | Itens Jellyfin permitidos ao utilizador | Scope de sessão/Jellyfin |
| GET | `/library/{id}/playback-options` | Verificação de acesso, fontes e pistas | Não devolver segredo global |
| POST | `/playback/sessions` | Criar sessão de reprodução com origem/perfil | Verificar autorização e política codec/transcode |
| PATCH | `/playback/sessions/{id}/progress` | Registar progresso consistente | Dono da sessão apenas |
| GET | `/discover/premieres?region=&kind=` | Estreias externas com fonte/data | Cache e limites de fontes |
| GET | `/catalog/{id}/trailers` | Trailers oficiais associados | Apenas urls/plataformas aprovadas |
| PUT/DELETE | `/me/follows/{catalogId}` | Seguir/retirar seguimento | Conta própria |
| POST | `/requests` | Pedido agregado por obra | Sem download implícito; rate limit |
| GET | `/me/requests` | Acompanhar os próprios pedidos | Não revelar requerentes alheios |
| PATCH | `/admin/requests/{id}` | Aprovar/adiar/rejeitar | Owner/admin NOVA apenas |
| GET/PUT | `/me/watchlist` | Consultar/adicionar à fila | Conta própria |
| POST | `/me/watchlist/reorder` | Reordenação atómica | Validar todos os itens de entrada |
| GET/POST | `/me/sessions` | Calendário e criação de sessões | Conta própria |
| PATCH | `/me/sessions/{id}` | Alterar data/hora/convidados | Proprietário do evento |
| POST | `/sessions/{id}/rsvp` | Responder a convite | Apenas convidado |
| GET | `/me/notifications` | Mensagens opt-in, sem duplicados | Conta própria |
| GET | `/admin/health` | Diagnóstico de fontes/serviços | Owner/admin NOVA |

**Semântica de erros:** `401` autenticação inválida; `403` ação não permitida sem revelar recurso sensível; `404` recurso inexistente ou privado consoante contexto; `409` conflito/duplicação; `422` validação; `424/503` indisponibilidade de dependência (apenas se apropriado); `429` limite de solicitações. Incluir código de erro estável, causa do lado do servidor não sensível e solução UI (Retry/Back/Alternative).

**Contrato de ficha (shape ilustrativo)**

```json
{
  "catalogId": "uuid",
  "kind": "movie",
  "title": "Terras de Sal",
  "publication": {"state": "released", "region": "PT", "date": null},
  "library": {"state": "available", "authorized": true, "playable": true},
  "actions": {"play": true, "follow": true, "request": false, "watchlist": true, "schedule": true},
  "images": {"poster": "image-proxy-ref", "backdrop": "image-proxy-ref"},
  "progress": {"positionMs": 0, "durationMs": null}
}
```

Os campos da simulação não são dados reais do Jellyfin nem criam direitos de utilização das imagens.

## 5. Sincronização de duas ou mais origens

**Padrão:** Jellyfin indexa pastas montadas read-only; a NOVA consulta inventário autorizado e reconcilia; eventos/webhooks servem para **acelerar**, não como única fonte de verdade; job periódico revalida.

1. Montar A e B separadamente no serviço Jellyfin com direitos mínimos; na configuração das bibliotecas, uma biblioteca pode incorporar vários diretórios; não usar biblioteca Mixed como solução geral quando existirem filmes/séries identificáveis.
2. Guardar `media_origin` por mount/volume/estado; detetar offline sem remover `catalog_item`, watchlist, pedidos ou agenda.
3. Incremental scan recolhe IDs Jellyfin, tipo, fornecedor, season/episode, media sources e tags de imagem.
4. Match por provider ref verificado; depois por metadados estruturados conservadores; `ambiguous` para revisão humana.
5. Para duas versões do mesmo filme, consolidar `catalog_item` e manter `media_asset` separados. Para episódios não confundir diferentes S/E.
6. Se novo `media_asset` preencher pedido, calcular interesses autorizados e criar notification event com dedup key estável.
7. Reconcile periódico encontra apagamentos, movidos, mudanças de ID, acessos alterados e falhas de eventos.
8. Não borrar historicamente itens só porque a origem A ou B deixou de responder; indicar `source_offline`.

**Mínimo de testes:** ficheiro só em A, só em B, duplicado em ambos, mesmo filme duas resoluções, temporadas em pastas diferentes, ficheiro renomeado, pasta B temporariamente offline, item removido, permissão do familiar alterada.

## 6. Playback e Direct Play

**Sequência do cliente Android TV**:
`tap Play -> NOVA API valida conta e permissão Jellyfin -> procura versão reproduzível -> avalia deviceCodecProfile/legendas/áudio/bitrate -> cria sessão autorizada -> Media3 prepara stream -> reporta progresso -> revalida ao retomar se necessário`.

Regras:
- Direct Play preferencial e máximo aproveitamento do descodificador do dispositivo.
- Remux sem conversão de vídeo quando o contentor for incompatível, quando tecnicamente aplicável.
- Transcode áudio/legendas apenas conforme capacidades e efeitos sobre vídeo conhecidos.
- **Vídeo transcode nunca iniciar sem o modo explicitamente configurado/autorizado**; mostrar problema compatibilidade e opções.
- Tokens de acesso de media não devem aparecer em logs, thumbnails ou analytics; o cliente não recebe credencial do administrador.
- A compatibilidade real não é garantida pela designação de codec: verificar hardware Xiaomi e Media3 nas oito provas G2.

## 7. Frontend modular e design system

App TV (Kotlin): `core/design`, `core/navigation`, `core/network`, `core/auth`, `core/player`, `feature/home`, `feature/library`, `feature/details`, `feature/discover`, `feature/premieres`, `feature/watchlist`, `feature/planner`, `feature/profile`, `feature/settings`.

- Os mesmos dados de domínio podem alimentar 1080p e 720p através de **tokens e layouts próprios**, sem simplesmente escalar o ecrã.
- D-pad garante foco restaurado ao voltar de detalhes/player, Back contextual, overlays com focus trap previsível e scroll que não esconde foco.
- Estados UI por recurso: `loading`, `ready`, `empty`, `partial`, `offline`, `error`, com ação útil.
- Ecrãs de admin não entram na navegação principal TV; backend prepara NOVA Control separado.

## 8. Motor Smart — contrato inicial

```text
input = { accountId, catalogScope, timeBudget, unseen, mood, genres,
          allowedSources, existingProgress, currentDevice, region,
          watchlistRank, seriesFollowing, explicitExcludedItems }
output = { primary?, alternatives[0..2], explanation[], coverage,
           constraintsApplied[], fallbackReasons[], generatedAt }
```

- Priorizar disponibilidade para sugestões de reprodução; títulos externos só se filtro permitir.
- 1 sugestão principal + 2 alternativas **distintas** quando houver opções suficientes; explicar relaxamento quando não há 3.
- Time budget inicial ≤120min; nunca mudar silenciosamente para >120min.
- Watchlist manual pesa positivamente, mas nunca é modificada pelo algoritmo.
- Dados por perfil; nenhuma sugestão usa dados privados de outras pessoas.
- Fixture reprodutível: mesma entrada e versão de regras -> mesmo resultado, com opção Surpreende-me usando semente controlada.

## 9. Segurança, privacidade e conformidade

- Private network + separate NOVA Gateway; sem exposição de TrueNAS, SMB, SSH ou acesso lateral à LAN.
- Zero trust prático: no acesso remoto, VPN identifica dispositivo/rede, mas cada endpoint exige autorização do utilizador.
- `owner` e `family` são papéis diferentes; `owner` NOVA não herda automaticamente o token root do NAS.
- Segurança por conta e por biblioteca: validação no backend e no Jellyfin, inclusive URLs de media, imagens e metadados privados.
- Gestão de sessões/tokens cifrada em repouso; secrets fora da base de código e auditável rotação/revogação.
- Políticas de retries, idempotência, rate limiting, revogação e migrações de BD com rollback.
- TMDB/YouTube: preservar atribuição, condições de imagem, branding e player. Licenciamento de fontes de anime carece revisão.
- Backups de configuração, dados NOVA e fotos geridos separadamente, com ensaio de restauro.

**Gate remoto não executado:** teste real com dispositivo familiar: HTTP para NOVA permitido; tentativas TrueNAS UI, SMB, SSH e outras subredes devem falhar. Portas/router não alteradas nesta fase.

## 10. Critérios de aceitação da F01 — verificáveis antes de código de produto

| Teste | Esperado | Estado |
|---|---|---|
| ARC-01 | Diagrama com limites de confiança e módulos documentados | Desenhado — por validar |
| ARC-02 | Identidade externa e Jellyfin dissociadas por IDs | Especificado — por validar |
| ARC-03 | Duas origens A/B com offline, duplicados e versões | Especificado — por validar |
| ARC-04 | Operações de media exigem verificação de permissões por conta | Especificado — por validar |
| ARC-05 | Endpoints rascunhados para 5 jornadas principais | Especificado — por validar |
| ARC-06 | Estado e eventos de pedido/seguimento/planner ortogonais | Especificado — por validar |
| ARC-07 | Modelo de playback explicitamente seguro e controlado | Especificado — por validar |
| ARC-08 | Recuperação offline/erro/ausência sem ação morta | Especificado — por validar |
| ARC-09 | Módulos de TV separados e design system reaproveitável | Especificado — por validar |
| ARC-10 | Riscos e decisões em aberto rastreáveis | Especificado — por validar |

A **F01 não pode ser considerada concluída** sem revisão e aprovação do modelo de dados, permissões, contratos e stack. Este documento é uma entrega técnica de design/planeamento.

## 11. Backlog F01 rastreável (tarefas reais de design técnico)

| ID | Tarefa | Gate / evidência | Estado |
|---|---|---|---|
| F01-001 | Confirmar os dois diretórios (mesmo NAS/equipamentos distintos) | Topologia assinada | Aberto |
| F01-002 | Escolher stack final do serviço NOVA | ADR-001 | Aberto |
| F01-003 | Definir deployment/containers e dados persistentes | ADR-002 + diagrama | Rascunho |
| F01-004 | Fechar bounded contexts e dependências | Diagrama aprovado | Rascunho |
| F01-005 | Modelo de identidade `catalog_item`/`provider_ref` | Esquema com unicidades | Rascunho |
| F01-006 | Modelo `media_origin`/`media_asset`/`catalog_match` | Esquema A/B/offline | Rascunho |
| F01-007 | Modelo conta/perfis/tokens/roles | Threat model e esquema | Rascunho |
| F01-008 | Modelo de follow/request/interest | Ciclo e constraints | Rascunho |
| F01-009 | Modelo de fila e calendário | Ordem, TZ, RSVP | Rascunho |
| F01-010 | Modelo de notif/outbox/auditoria | Dedup + retenção | Rascunho |
| F01-011 | Contrato da API de catálogo | OpenAPI revisto | Rascunho |
| F01-012 | Contrato API de reprodução/progresso | OpenAPI revisto | Rascunho |
| F01-013 | Contrato API de pedidos/seguimentos | OpenAPI revisto | Rascunho |
| F01-014 | Contrato API de Planner | OpenAPI revisto | Rascunho |
| F01-015 | Política concreta de autenticação Jellyfin-NOVA | ADR-003 + sequência | Aberto |
| F01-016 | Estratégia sync eventos/reconcile | Estados, retries, jobs | Rascunho |
| F01-017 | Regras de match e deteção de duplicados | Fixtures com conflitos | Rascunho |
| F01-018 | Política de imagens e TMDB com atribuição | ADR-004 + testes | Rascunho |
| F01-019 | Política de trailers oficiais | ADR-005 | Aberto |
| F01-020 | Contract SmartPick e privacidade | Fixtures/algoritmo | Rascunho |
| F01-021 | Definição de capacidades TV codecs/D-pad | Matriz G2 | Rascunho |
| F01-022 | Matriz de autorização e ameaças | Testes negativos planeados | Rascunho |
| F01-023 | Decidir foco APK A/escopo mínimo | Sprint inicial fechado | Aberto |
| F01-024 | Plano de migrações de DB e backup | Restauração experimental | Aberto |
| F01-025 | Rever aceitação F00 e F01 com proprietário | Gate de aprovação | Aberto |

## 12. Decisões técnicas pendentes (ADR)

- **ADR-001:** FastAPI/Python vs Kotlin/Ktor para backend. Defaults propostos: FastAPI pela simplicidade do ecossistema, contratualização OpenAPI e administração posterior React; decisão não aplicada.
- **ADR-002:** API + worker + PostgreSQL em rede interna isolada; persistência com snapshots e cópia externa; destino de deployment por confirmar.
- **ADR-003:** Associação segura de identidade NOVA/Jellyfin, sem token global no cliente. Rever Quick Connect, renovação e revogação de sessões.
- **ADR-004:** TMDB para metadados públicos com fonte/atribuição/cache; fallback Jellyfin local e revisão de limites/licenças.
- **ADR-005:** Player oficial para trailers, evitando implementar extração/download de vídeos.
- **ADR-006:** Acesso remoto familiar por rede privada/gateway isolado; tecnologia concreta deliberadamente adiada.

## 13. Próxima entrega realizável

**F01.1 (protótipo técnico):** diagramas Figma de módulos/trust boundaries, domínio e entidades, pipeline das duas origens, sequência de autorização/streaming, estados de falha e roadmap testável. **F01.2 (a decidir):** stack e primeiro contrato OpenAPI/BD após rever as opções. **F02/F03 continuam por iniciar** até gate arquitetural.

## 14. Fontes técnicas oficiais consultadas

- Jellyfin Libraries: https://jellyfin.org/docs/general/server/libraries/
- Jellyfin Movies / versions: https://jellyfin.org/docs/general/server/media/movies/
- Jellyfin Networking: https://jellyfin.org/docs/general/networking/index.html
- TMDB finding data: https://developer.themoviedb.org/docs/finding-data
- TMDB images: https://developer.themoviedb.org/reference/movie-images
- Tailscale grants: https://tailscale.com/docs/reference/syntax/grants

**Aviso:** estas fontes sustentam decisões de arquitetura; nenhum endpoint real, credencial, token, ficheiro do NAS ou ligação remota foi verificado neste turno.
