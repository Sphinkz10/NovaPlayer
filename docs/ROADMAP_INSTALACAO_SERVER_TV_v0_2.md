# NOVA — Roadmap até à instalação no servidor e na TV

**Atualização:** 22-10-2026. M3 de software concluída em laboratório. Acompanhamento único: [M3_FECHO.md](M3_FECHO.md).

**Fase em execução:** [M4 — Distribuição Android](M4_DISTRIBUICAO_ANDROID.md), após instalação LAN, catálogo/player e recuperação integrada. A APK tem identificador próprio, debug desativado e assinatura persistente offline; o servidor mantém a imagem verificada. Próximo gate M4: ensaio físico das duas origens em cada box. Guardar a cópia offline da chave de assinatura separadamente da palavra-passe.

**Incremento M5:** [gateway Docker e percurso WireGuard](M5_GATEWAY_CONTENTOR.md). O gerador prepara cinco serviços e os certificados; o gateway cria a interface e aplica aprovações/revogações do Control; a TV obtém parâmetros públicos pela API e usa o motor nativo para catálogo/player. A preparação/renovação do perfil de 24 horas ainda exige LAN. Consultar o guia para resultados e pacote verificado.

**Próximos passos para fechar M5:** (1) integrar renovação/descoberta remota e recuperação cifrada do perfil de cinco serviços; (2) concluir autenticação, ligação, reprodução e revogação nativas com Tailscale; (3) concluir o mesmo com NetBird; (4) validar rede externa e os dois aparelhos físicos. Compilar as bibliotecas dos fornecedores não satisfaz estes critérios.

| Quando instalar/testar | O que permite |
|---|---|
| Servidor de teste — M2 | Configurar proprietário, Jellyfin e duas origens; imagem Docker e recuperação já ensaiadas. TrueNAS físico continua pendente |
| APK de laboratório — M3 | Login Directory, aprovação e bibliotecas atribuídas; sem reprodução. M3 de software concluída: sete critérios e pacote verificados |
| Instalação LAN de teste — M4 | Gerar estado/YAML no PC, instalar nas Apps, configurar a própria TV e ensaiar catálogo/player separadamente na Xiaomi Box S2 e no Chromecast |
| Ensaio WireGuard — incremento M5 | Pacote novo de cinco serviços e APK 0.10; preparação inicial na LAN, perfil de 24 horas e endpoint UDP alcançável. Resultados e limites no guia M5 |
| Utilização remota familiar — M5 completa | Descoberta/renovação, recuperação e jornadas nativas WireGuard, Tailscale e NetBird; cada fornecedor precisa da própria prova |

Já podes preparar uma instalação LAN **nova e de teste** seguindo o guia da entrega, com recuperação completa ensaiada em Docker e identidade persistente da APK. Não há data de conclusão física M4/M5 confirmada: a M4 exige reprodução nos dois aparelhos; a M5 exige os três fornecedores nativos.

**Requisito incorporado:** WireGuard, Tailscale e NetBird são opções nativas do NOVA Connect. O proprietário configura a ligação no NOVA Control. A TV instala a NOVA Cinema e recebe a configuração autorizada através da associação de dispositivo. Instalar outra app VPN na TV não satisfaz o objetivo de integração nativa deste roadmap.

**Entrega atual — M4 LAN com recuperação:** assistente no PC sem Docker/SSH, YAML de quatro serviços, três endpoints HTTPS no IP privado e Jellyfin sem porta publicada. O Control configura bibliotecas, publica no Directory e cria familiares; a TV valida o fingerprint e configura-se pela própria UI. O formato 2 inclui o estado NOVA/Directory/Jellyfin/TLS, com nova publicação, permissões e aprovação após restauro. [Guia e resultados](M4_RECUPERACAO_LAN.md). A [recuperação M2](M2_TRUENAS_RECUPERACAO.md) conserva o formato legado. A transferência e os ACL do NAS são manuais; o restauro cria um destino novo, conservando identidades.

**Execução iniciada:** [fase 1](FASE_1_RESULTADOS.md) e [ADR 001](ADR_001_CONNECT_NATIVO.md). Correções e contratos implementados; gates Linux e Docker aprovados na CI. M0 permanece aberto até à prova de incorporação e HTTPS dos três motores. Os modelos indicados são aparelhos de aceitação, não uma lista que limita o produto: a compatibilidade é decidida por SDK, ABI, recursos e capacidades de reprodução. A recolha das versões exatas acontece no ensaio de instalação, sem bloquear o desenvolvimento da base.

Alvos confirmados pelo proprietário: **TrueNAS Community**, **Xiaomi TV Box S de 2.ª geração** e **Chromecast com Android TV**, conforme a identificação fornecida. O modelo/geração exatos do Chromecast continuam por confirmar; não assumir variante HD ou 4K. Confirmar também versão/build do TrueNAS, CPU/arquitetura, ACL dos datasets e versões Android antes de escolher os pacotes de instalação. A versão concreta do TrueNAS determina o mecanismo suportado de instalação; não modificar o sistema base do NAS para contornar as suas restrições.

### Matriz de dispositivos do primeiro lançamento

| Alvo | Obrigação de validação | Informação em falta |
|---|---|---|
| TrueNAS Community | Instalação suportada pela versão, datasets read-only, persistência, rede e backup/restauro | Versão/build, hardware, caminhos e ACL dos datasets |
| Xiaomi TV Box S de 2.ª geração | Instalação da APK, comando, associação, reprodução e os três motores de ligação | Versão Android e capacidades reais observadas |
| Chromecast com Android TV | Instalação da APK, comando, associação, reprodução e os três motores de ligação | Modelo/geração, versão Android e capacidades reais observadas |

Uma aplicação NOVA Cinema com suporte aos dois dispositivos é o objetivo inicial. Selecionar as bibliotecas nativas/ABIs necessárias após identificar o hardware e negociar capacidades de reprodução por dispositivo. A aprovação na Xiaomi não aprova automaticamente o Chromecast: codecs, resolução, HDR, áudio, memória e reconexão têm resultados próprios. O marco de suporte integral exige **seis combinações de teste remoto: dois dispositivos × três fornecedores**.

## 1. Resultado pretendido

**No servidor:** instalar NOVA Server; abrir NOVA Control; criar proprietário; selecionar duas ou mais origens read-only; configurar Jellyfin no mesmo percurso; escolher WireGuard, Tailscale ou NetBird; autorizar TV; ver saúde, ligação, dispositivos e revogação.

**Na TV:** instalar NOVA Cinema; abrir; associar por código/QR aprovado num telemóvel; selecionar servidor quando houver mais de um autorizado; carregar biblioteca; reproduzir e retomar. Endereços, rotas e chaves não são introduzidos pelo familiar. A autorização inicial da VPN do Android pode ser necessária.

**Entrega completa deste âmbito:** pacote de servidor e APK assinada, com cada um dos três fornecedores demonstrado individualmente de ponta a ponta. Uma opção no menu, um container iniciado ou uma APK compilada não fecham essa entrega.

## 2. Base existente

Auditoria do commit `57391fcc64e9e65220d6ed59f02dfa98f052db38`: 61 ficheiros locais iguais ao GitHub; servidor executável por HTTP; 51/53 testes Python aprovados em Windows, com duas falhas de caminhos Linux; 131/131 testes Kotlin; 11/11 verificações heurísticas; APK Connect debug compilada. Nenhum Docker/TrueNAS, handshake VPN, biblioteca ou vídeo reais demonstrados.

**Achados históricos da auditoria inicial, entretanto corrigidos na fase 1:** o painel tinha um erro de login reproduzido. O diagnóstico Python aceitava falsos ready, as origens eram mostradas sem medição, o limite de login tinha uma corrida e havia dependências a atualizar. Consultar o relatório `AUDITORIA_NOVA_2026-10-17.md`, na pasta principal do workspace.

## 3. Contrato de integração nativa

| Capacidade | WireGuard | Tailscale | NetBird |
|---|---|---|---|
| Configuração no NOVA Control | Gateway gerido pelo pacote ou associação a gateway existente suportado | Associar a uma tailnet autorizada; inscrição, tags e políticas | Associar ao serviço cloud ou a gestão self-hosted existente; inscrição, grupos e políticas |
| Implementação do lado servidor | Agente/serviço WireGuard isolado; helper de rede limitado quando necessário | Serviço oficial isolado ou componente incorporado; escolher após prova | Peer isolado, avaliando modo rootless e restrições de conectividade |
| Identidade de TV | Peer e chave próprios | Nó/identidade próprios do fornecedor | Peer/identidade próprios do fornecedor |
| Motor dentro da APK | Estender biblioteca Android já usada | Provar ponte Go/nativa e transporte Android | Provar biblioteca móvel a partir do projeto oficial e transporte Android |
| Diagnóstico | Estado + handshake recente + tráfego + HTTPS NOVA | Autenticação + peer/rota + direto/relay quando disponível + HTTPS NOVA | Autenticação + peer/política + direto/relay quando disponível + HTTPS NOVA |
| Revogação | Retirar peer e invalidar sessão NOVA | Revogar nó/autorização aplicável e sessão NOVA | Revogar peer/autorização aplicável e sessão NOVA |

O proprietário mantém a autorização da conta/rede do fornecedor; NOVA não a pode substituir. A automatização depende das APIs, permissões e condições efetivamente disponíveis. Credenciais administrativas do fornecedor permanecem no servidor e nunca entram na APK ou no Directory. Chaves de inscrição temporárias não devem tornar-se uma credencial partilhada por todas as TVs.

Cada fornecedor é um adaptador próprio. Todos usarem WireGuard no transporte não torna os seus perfis, autenticação ou mecanismos de descoberta intercambiáveis. Suportar Tailscale/NetBird cloud e a ligação a um NetBird self-hosted existente não significa instalar uma infraestrutura de gestão completa em cada NAS; essa instalação é uma entrega opcional posterior.

**Estados comuns propostos:** desativado, configuração necessária, autorização pendente, dispositivo pendente, a ligar, ligado, degradado, erro recuperável, revogado. Mostrar também o motivo e a ação de recuperação. “Ligado” exige chegar ao serviço NOVA com identidade e autorização válidas.

**Operações comuns propostas:** inspecionar capacidades, validar configuração, inscrever servidor/dispositivo, ligar, diagnosticar, desligar, revogar e rodar credenciais. Estas são operações de domínio com parâmetros validados; não um terminal de comandos livre através da API.

## 4. Fronteira de rede e segurança

- Separar a API administrativa da API de utilizador/media. A TV só recebe acesso aos endpoints necessários.
- Criar um gateway de media no servidor para API/streaming Jellyfin autorizados, incluindo Range, seek e eventos necessários. Definir allowlist de rotas e métodos; não fazer proxy indiscriminado da administração Jellyfin.
- Manter o Jellyfin e a administração fora da publicação direta na Internet. Servir o endpoint de cliente por HTTPS com identidade validada, inclusive na LAN.
- TLS de media termina no NOVA Server do proprietário. Relays de transporte não recebem as chaves que permitem ler esse fluxo. Não usar um proxy de relay que termine TLS de media fora do servidor.
- Preferir peers/serviços com endereço dedicado e ACL por porta. Uma rota /32 limita o destino, mas não impede aceder a todas as portas desse IP: testar firewall e autorização no servidor.
- Não anunciar toda a LAN, criar exit node ou encaminhar tráfego geral da TV por defeito. Negar TrueNAS UI, SMB, SSH, administração NOVA e outras instâncias.
- Isolar os agentes dos fornecedores; conceder capacidades de rede apenas onde comprovadamente necessárias. Não dar `privileged` ao NOVA Core, acesso geral ao socket Docker ou comandos arbitrários no host.
- Escolher modos userspace/rootless ou TUN após medir compatibilidade e desempenho. Rootless não é sinónimo de isolamento verificado nem garantia de 4K.
- Uma TV usa um fornecedor ativo para o servidor selecionado na primeira versão. Mudança de fornecedor deve desligar e limpar o anterior, revalidar identidade e preservar apenas dados autorizados. Sem fallback público ou mudança silenciosa para outro fornecedor.
- WireGuard direto exige um endpoint alcançável. CGNAT/NAT podem impedir essa rota; nesse caso apresentar indisponibilidade e uma alternativa autorizada. Não prometer que WireGuard puro resolve NAT traversal ou relay automaticamente.
- O conflito com outra VPN deve ter explicação e recuperação. Nunca tentar contornar o consentimento do Android.

## 5. Roadmap de execução

Os números identificam marcos verificáveis; as versões abaixo são propostas. Não são datas prometidas. A prova inicial dos três motores precede o investimento na experiência final para revelar cedo limitações técnicas.

| Marco | Trabalho | Critério de conclusão | Resultado instalável |
|---|---|---|---|
| M0 — Arquitetura e provas de integração | Contratos Server/Cinema/Directory; topologia de rede; provas Android WireGuard, Tailscale e NetBird | Cada motor compila dentro de uma APK e chega por HTTPS a um serviço de teste; enrollment, consentimento, tamanho, ABI, licenças dos componentes e manutenção documentados | APKs internas de prova; sem distribuição familiar |
| M1 — Estabilizar base, v0.1.1 | Corrigir achados da auditoria; testes Linux e navegador; Gradle Wrapper; dependências fixadas; CI | Bootstrap/login/diagnóstico/sessões corretos, limite concorrente validado, análise de dependências revista, builds reproduzíveis | Pacotes de laboratório reproduzíveis |
| M2 — NOVA Server instalável, v0.2 | Compose real; assistente proprietário/Jellyfin/bibliotecas; preflight TrueNAS; ACL; volumes; backup/restauro | Duas origens lidas e indexadas, escrita bloqueada, reboot e persistência aprovados; configuração concluída no Control | **Primeira instalação do servidor em ambiente de teste** |
| M3 — Identidade, dispositivos e Directory mínimo, v0.3 | Registo de servidor; associação conta/servidor; autorização por código; sessões/refresh; permissões Jellyfin; identidade TLS | TV recebe autorização limitada e descriptor autenticado; conta não autorizada é recusada; dispositivo revogado perde novas autorizações | Servidor pronto para emparelhar o cliente de teste |
| M4 — NOVA Cinema local, v0.4 | UI TV essencial, D-pad, biblioteca real, fichas, Media3, faixas e progresso | Instalar na Xiaomi e no Chromecast Android TV; login, filme real de A/B, Direct Play observado e retoma após reabertura em cada dispositivo | **Primeira instalação útil nos dois dispositivos, na rede local** |
| M5-W — WireGuard nativo | Wizard servidor/gateway existente suportado; peer por TV; motor integrado; firewall; revogação | Login → ligação → catálogo → vídeo numa rede externa; handshake e isolamento observados | Versão de teste remoto por WireGuard |
| M5-T — Tailscale nativo | Inscrição e política da tailnet; identidade por TV; motor integrado; caminho direto/relay | Mesma jornada externa dentro da NOVA Cinema; ACL e revogação verificadas | Versão de teste remoto por Tailscale |
| M5-N — NetBird nativo | Cloud/gestão própria existente; peers/grupos/políticas; motor integrado; diagnóstico | Mesma jornada externa dentro da NOVA Cinema; política e revogação verificadas | Versão de teste remoto por NetBird |
| M6 — Integração e ensaio pessoal, v0.5 | Descoberta sem IP, recuperação de rede, troca controlada de fornecedor/servidor, estabilidade e desempenho | Seis combinações Xiaomi/Chromecast × WireGuard/Tailscale/NetBird concluídas com o TrueNAS real; medições e testes negativos preservados | **Pacote para instalação pessoal nos dois dispositivos com os três modos suportados** |
| M7 — Candidato para convidados, v0.6-rc1 | Gates SEC; recuperação de chaves; backup/restauro; atualização/rollback; revisão independente | SEC-01…12 com evidências e riscos resolvidos/aceites explicitamente; instalação limpa e upgrade testados | Versão candidata a utilização por familiares; publicação geral é uma decisão posterior |

M5-W → M5-T → M5-N é a ordem recomendada de implementação: aproveita a base WireGuard e mantém cada integração verificável. M0 testa a viabilidade dos três logo no início. O marco de suporte integral permanece aberto até os três passarem; usar apps VPN externas pode servir de diagnóstico, mas não fecha estes marcos.

### M0 — Resolver cedo a parte difícil

1. Recolher automaticamente SDK/ABI/capacidades e preparar a matriz por dispositivo. Registar versão/build do TrueNAS e topologia durante o ensaio de instalação, incluindo alcance do endpoint WireGuard direto.
2. Construir um ensaio mínimo para cada motor com credenciais descartáveis, HTTPS e serviço de teste, sem adicionar catálogo/player nessa prova.
3. Para Tailscale, avaliar componente Go/nativo incorporado versus serviço de transporte por aplicação. A existência de `tsnet`/`libtailscale` não demonstra automaticamente compatibilidade Media3/Android TV.
4. Para NetBird, compilar e avaliar a biblioteca móvel do projeto oficial; selecionar exatamente os componentes incorporados e as obrigações de distribuição correspondentes.
5. Escolher o ponto de entrada de rede da APK: sockets/fábrica de transporte por aplicação quando viável ou VPN Android com consentimento. Se houver proxy local, restringi-lo à app e não criar um proxy aberto.
6. Registar decisão técnica para cada motor: versão/commit, ABIs, API usada, ciclo de vida, autenticação, privacidade, atualização e evidência do pedido HTTPS.

**Bloqueio explícito:** se um motor não passar a prova de incorporação, manter esse requisito aberto e rever a abordagem. Não apresentar a instalação de outro cliente VPN como se fosse integração nativa concluída.

### M1/M2 — Instalar o servidor sem adivinhar o estado

Corrigir o formulário do Control, o contrato de saúde e a concorrência do login. Implementar healthchecks, recuperação de falhas e migrações versionadas. Criar instalação que não substitui dados/segredos existentes e suporta retoma após falha parcial.

O assistente deve criar proprietário, configurar/associar Jellyfin, ligar duas ou mais origens, mostrar a indexação e confirmar permissões. Evitar dois percursos de configuração concorrentes. A conta NOVA associa-se à identidade Jellyfin por um contrato explícito; tokens administrativos não são entregues à TV.

Definir storage persistente e permissões por dataset, recursos mínimos medidos, versões suportadas e cópias cifradas de configuração/dados sensíveis. A chave de recuperação tem destino separado do backup. Um restauro de teste deve recuperar a administração sem recuperar acidentalmente autorizações revogadas.

**Aceitação física:** ficheiro em A, ficheiro em B, duplicado, origem B offline, NAS reiniciado, imagem atualizada e regressão de versão com restauro quando a migração o exigir. Falta de uma origem não apaga listas/histórico.

### M3 — Identidade independente da VPN

**M3 concluída no software de laboratório:** login Directory na TV, prova de conta, aprovação, continuidade TLS, bibliotecas Jellyfin limitadas, renovação e revogação. Os sete critérios e evidências estão consolidados em [M3_FECHO.md](M3_FECHO.md).

**Prova de 19-10-2026:** associação Android aprovada em emuladores API 26 e 35, com 11 etapas cada. Já existe APK para ensaiar associação em laboratório com o PC; não liga automaticamente ao NAS nem reproduz filmes. A primeira utilização local com biblioteca e vídeo continua a ser M4. Aceitação física das boxes e do TrueNAS permanece pendente.

**Directory:** serviço privado integrado com o Control e a TV, renovação limitada e revogável e continuidade de confiança aprovadas em laboratório. Não foi publicado na Internet. Os guias de incrementos anteriores são históricos.

O Directory autentica, associa conta e servidor e fornece descoberta autenticada; não recebe biblioteca, histórico, vídeo ou segredos administrativos dos fornecedores. Registar servidor com chave própria e prova de posse. Desenhar disponibilidade e recuperação do Directory; reprodução local já associada deve ter uma política explícita para indisponibilidade do serviço.

A TV apresenta código/QR com validade curta. A aprovação verifica conta, servidor e dispositivo. Implementar proteção contra repetição, polling limitado, códigos expirados, refresh rotativo e revogação. Cada chamada privada continua sujeita às permissões do utilizador e do Jellyfin.

Escolher e testar a confiança TLS inicial, renovação e recuperação após perda/troca de certificado. O canal de descoberta não pode mandar a TV confiar cegamente num servidor diferente. Não desativar validação TLS para facilitar a instalação.

### M4 — Primeira app de TV que reproduz

Âmbito mínimo: associação/login, Home simples, Filmes/Séries, pesquisa, detalhe, reprodução e retoma, áudio/legendas, erro/offline e logout. Reaproveitar o design existente onde encaixa; não bloquear o primeiro filme pela implementação de Planner ou Smart.

Separar compatibilidade de contentor, codec áudio, vídeo e legendas. Distinguir Direct Play, remux, conversão só de áudio e vídeo transcode autorizado. Observar o método real no Jellyfin. Medir os testes G2 no hardware, incluindo formatos suportados e falhas; não declarar 4K/HDR/áudio multicanal apenas com base numa ficha técnica.

Identificador `com.novacinema.cinema` e chave persistente de assinatura preparados na [distribuição Android](M4_DISTRIBUICAO_ANDROID.md), com banner/ícone e manifest TV. A chave privada permanece fora do Git/CI. Confirmar a guarda offline e ensaiar foco/Back, suspensão e reabertura no hardware. A APK debug de laboratório mantém uma identidade separada.

### M5 — Três fornecedores, a mesma experiência

**WireGuard:** geração de chaves por dispositivo, gateway gerido ou perfil restrito para gateway existente suportado, endereço/porta e alcance verificados, keepalive quando necessário, rota mínima e firewall por serviço. Registar peer no gateway real; importação de um ficheiro não prova aprovação remota. Automatizar gateways externos apenas quando houver uma API/adaptador concretamente suportado.

**Tailscale:** autenticação autorizada pelo proprietário, servidor/nó de TV próprios, política mínima, aprovação conforme a tailnet, expiração e remoção de nó. Desativar funcionalidades de exposição pública. Medir desempenho direto e via relay sem assumir bitrate garantido.

**NetBird:** URL de gestão cloud/self-hosted validada, inscrição individual, grupos dedicados, políticas restritas, persistência de peer e revogação. Remover/revogar o peer efetivamente; expirar a setup key não equivale a retirar o acesso de um peer já inscrito. Medir transporte userspace/rootless e caminho de relay.

Para os três: gestão no Control, configuração idempotente, diagnóstico, alteração de credenciais, remoção de dispositivo, erro recuperável e logs sem tokens. Provar que o client API/gateway não expõe endpoints administrativos ou uma rota geral para o NAS.

### M6/M7 — Critérios para usar e para convidar

**Instalação pessoal:** release de servidor e APK assinada, instruções específicas da plataforma, backups/restauro ensaiados, três modos completos e matriz de rede/hardware aprovada. O ensaio deve incluir pelo menos 24 horas de operação com suspensão, reconexão, seek e troca de redes, além de utilização normal; duração é um limiar proposto, não uma prova isolada de estabilidade.

**Antes de familiares:** executar os 12 gates da arquitetura de segurança, incluindo revisão independente, e definir limites de utilizadores/bitrate a partir de medições. Revogação deve bloquear novas autorizações e terminar ligações/sessões ativas dentro de um SLA definido e testado; alvo inicial proposto: até 60 segundos quando os extremos estão online. Offline: credenciais de curta duração e revalidação ao voltar a ligar, sem prometer revogação instantânea num extremo inacessível.

## 6. Matriz mínima por fornecedor

Executar esta matriz separadamente na Xiaomi TV Box S de 2.ª geração e no Chromecast com Android TV, preservando identificação do dispositivo e versão do sistema em cada resultado.

| Prova | Resultado exigido |
|---|---|
| Servidor + TV em redes distintas | Associação autorizada, catálogo e vídeo reais |
| Identidade TLS alterada ou servidor errado | Ligação bloqueada; sem downgrade |
| NAS UI, SSH, SMB, outras portas/hosts | Acesso negado pela rede e pelas fronteiras de serviço aplicáveis |
| Conta A e biblioteca de B | Não listar, obter imagens ou reproduzir conteúdo sem autorização |
| Revogar TV durante reprodução | Encerrar autorização/ligação conforme SLA e impedir nova sessão |
| Apagar/rodar inscrição do fornecedor | Verificar estado real do peer e impedir credenciais partilhadas |
| Reboot servidor e TV; perda de rede | Reconexão segura, sem segredo perdido nem fallback público |
| Outra VPN ativa no Android | Conflito explicado; nenhuma tentativa de contornar o sistema |
| Trocar fornecedor | Desligar motor anterior e revalidar identidade/autorização |
| Direct Play e seek | Filme real, Range correto, progresso e método de playback observados |
| Direto/relay/NAT difícil | Mostrar o caminho disponível e medir bitrate/latência; WireGuard direto pode ficar indisponível |
| Segunda instalação NOVA | Nenhuma associação ou permissão atravessa servidores indevidamente |

## 7. Como fica a instalação final

**Proprietário:** instalar pacote compatível → abrir NOVA Control → criar conta → escolher origens → configurar Jellyfin → escolher fornecedor → autorizar a rede/conta quando exigido → testar ligação → aprovar TV.

**TV:** instalar NOVA Cinema → abrir código/QR → aprovar no telemóvel → aceitar VPN Android quando exigido → biblioteca → reproduzir. Reabertura usa uma sessão válida e verifica novamente o contexto de acesso.

**Marcos de instalação:** servidor em laboratório no M2; TV com reprodução local no M4; instalação pessoal com WireGuard, Tailscale e NetBird nativos no M6; convidados apenas após M7. Não é preciso implementar estreias, pedidos, Planner e Smart para chegar a esses marcos. Esses módulos ficam no roadmap de produto posterior.

## 8. Primeira sequência de trabalho

1. Confirmar os alvos e preparar contratos/provas de incorporação dos três motores (M0).
2. Corrigir a base auditada e criar CI Linux/Android reproduzível (M1).
3. Fechar a instalação real e o wizard do servidor (M2).
4. Implementar identidade/Directory mínimo e TV local com um filme real (M3/M4).
5. Concluir e provar WireGuard, Tailscale e NetBird, cada um com revogação e isolamento (M5).
6. Empacotar, medir em hardware e executar segurança antes de convidados (M6/M7).

Não atribuir datas fixas antes de M0/M2: integração nativa Tailscale/NetBird, compatibilidade TrueNAS e medições da TV ainda são dependências não demonstradas. Estimar esforço por marco depois dessas provas, sem transformar APK compilada em promessa de produto pronto.

## 9. Fontes técnicas verificadas

As fontes seguintes sustentam os pontos de integração; a arquitetura e os critérios acima são propostas para a NOVA, ainda por implementar/testar.

- [WireGuard — incorporação e biblioteca Android](https://www.wireguard.com/embedding/): biblioteca Android oficial disponível para apps próprias.
- [Tailscale — tsnet](https://tailscale.com/docs/features/tsnet): incorporação em Go e rede userspace; autenticação mantém a autorização da tailnet.
- [Tailscale — libtailscale](https://github.com/tailscale/libtailscale): biblioteca C a avaliar na prova de incorporação; não tratada aqui como SDK Android pronto.
- [Tailscale — parâmetros Docker](https://tailscale.com/docs/features/containers/docker/docker-params): persistência, configuração e diferenças entre modos de rede.
- [NetBird — Docker](https://docs.netbird.io/get-started/install/docker): peer em container, modos de execução e limitações rootless.
- [NetBird — cliente Android e build da biblioteca móvel](https://github.com/netbirdio/android-client): código Android/Go e componentes a selecionar na integração.
- [Android — VPN](https://developer.android.com/develop/connectivity/vpn): consentimento, ciclo de vida, uma VPN ativa por utilizador/perfil e split tunneling.

Este documento satisfaz o planeamento do novo requisito. Não configura contas, não abre portas nem declara concluídas as integrações.
