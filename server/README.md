# NOVA Server 0.2.0-lab — M2

Base de segurança implementada em 17-10-2026: login Control corrigido, diagnóstico Jellyfin limitado a 16 KiB/4 s com validação de produto/wizard/identidade opcional, limite de login atómico, duas verificações Argon2 simultâneas por processo, dependências transitivas fixadas com hashes. Cinco falhas/tentativas em curso por origem durante 15 minutos; sucesso retira apenas a própria reserva e não apaga outras falhas. A administração aceita Host `localhost`/`127.0.0.1`.

O Control guarda **rascunhos** WireGuard/Tailscale/NetBird sem segredos nem ativação de rede. As origens mostram permissões/leitura/indexação ainda não verificadas. Para comparar a identidade Jellyfin com uma associação aprovada, definir `NOVA_JELLYFIN_SERVER_ID` no ambiente do Core; sem isso o diagnóstico devolve `identity_verified=false`.

Instalação Apps TrueNAS, imagem por digest, cópia cifrada, recuperação e reversão: [guia M2](../docs/M2_TRUENAS_RECUPERACAO.md). Aceitação no NAS físico pendente.

Novo incremento: [assistente M2](../docs/M2_SERVIDOR_LAB.md). Criação do proprietário pelo navegador, configuração Jellyfin, uma ou duas bibliotecas, retoma e contagens de indexação.

Testes e limitações anteriores: [fase 1](../docs/FASE_1_RESULTADOS.md). O restante percurso de instalação abaixo continua destinado a laboratório; não foi executado neste TrueNAS.

> **Estado:** primeira entrega funcional **de código**, NÃO uma versão pronta para famílias, nem uma instalação validada no TrueNAS. Não há ainda VPN, NOVA Directory, login universal nem APK NOVA Cinema. **Não publicar estas portas na Internet.**

## Para que serve

Este repositório prepara **um pacote** com dois serviços no mesmo Docker Compose:

- **Jellyfin oficial** (media server), com **dois diretórios** físicos montados em `/media/source-a` e `/media/source-b`, ambos **somente leitura**.
- **NOVA Core** (primeiro painel local NOVA Control), que cria um proprietário, guarda **hashes Argon2id**, gera sessões locais de 1 hora e diagnostica o estado do Jellyfin.

Quando terminarmos o produto, o proprietário só instalará NOVA Server e configurará os seus conteúdos, VPN e convidados pelo assistente. Os familiares só instalarão NOVA Cinema e farão login. **Esse fluxo completo ainda não está implementado.**

## Pré-requisitos (P01: Linux genérico com Docker Compose)

- Linux x86_64/arm64 com Docker Engine + `docker compose` instalado e ativo.
- Conta de serviço **não root** com permissão de executar o Docker (atenção: acesso ao grupo `docker` equivale frequentemente a privilégios elevados no anfitrião).
- Python 3.10+ no anfitrião apenas para os scripts de instalação e bootstrap.
- Dois diretórios de media existentes, com leitura para a conta usada na execução.
- Para operar remotamente o painel de administração, usar **túnel SSH administrativo**. Nunca abrir 8787 ou 8096 no router.

> **TrueNAS SCALE:** esta é uma base de Compose para Linux; a integração como instalação guiada nas Apps do TrueNAS e o modelo de permissões de datasets continuam por testar. Não instalar diretamente no TrueNAS de produção sem rever a compatibilidade da versão.

## Instalação passo a passo

1. Entrar na pasta `server/` das fontes atuais, ou na pasta do pacote de servidor extraído.
2. Confirmar que ambos os diretórios têm os ficheiros desejados (ou pastas vazias temporárias).
3. Verificar pré-requisitos e criar configuração, **sem utilizar root** (substituir pelos teus caminhos). A pasta do pacote deve ficar separada das duas origens de media:

   ```bash
   python3 scripts/preflight.py --media-a "/mnt/disco1/Filmes" --media-b "/mnt/disco2/Series"
   python3 scripts/install.py --media-a "/mnt/disco1/Filmes" --media-b "/mnt/disco2/Series"
   ```

   O instalador valida caminhos, cria `.env` em modo `0600`, diretórios de dados locais e token temporário de primeira instalação (`state/nova/bootstrap.token`, também `0600`). Recusa substituição acidental da configuração existente.

4. Arrancar os serviços:

   ```bash
   docker compose up -d --build
   docker compose ps
   ```

5. Abrir `http://127.0.0.1:8787` localmente ou através do túnel SSH abaixo. Criar o proprietário usando o código em `state/nova/bootstrap.token` e uma palavra-passe de pelo menos 14 caracteres. O código é consumido uma única vez. O script `first_run.py` continua disponível como alternativa no terminal.

6. Entrar com a conta NOVA e usar **Configurar o Jellyfin**. Indicar uma conta administrativa Jellyfin nova (palavra-passe de pelo menos 14 caracteres), ou as credenciais existentes para retomar. Escolher uma biblioteca para as duas origens ou duas bibliotecas separadas, com o tipo Filmes/Séries de cada uma. Os caminhos no contentor são fixos: `/media/source-a` e `/media/source-b`.

7. Aguardar a indexação e usar **Verificar indexação**, introduzindo novamente as credenciais Jellyfin. A NOVA guarda a última observação com data; não guarda a palavra-passe nem o token administrativo Jellyfin. As contas NOVA e Jellyfin continuam independentes. Bibliotecas incompatíveis são recusadas, sem apagar ou reconfigurar bibliotecas existentes. A configuração inicial desativa acesso remoto numa instalação Jellyfin nova e usa metadados locais; enriquecimento remoto pode ser configurado posteriormente no Jellyfin.

Não mudar a organização/nome das bibliotecas para tentar corrigir uma falha: retomar com os mesmos dados. Uma alteração de identidade Jellyfin bloqueia a operação e exige revisão manual da instalação; não apagar a base NOVA para contornar esse bloqueio.

### Gestão noutro computador através de SSH

Se o servidor não tiver navegador, no teu PC podes criar um túnel de administração:

```bash
ssh -L 8787:127.0.0.1:8787 -L 8096:127.0.0.1:8096 UTILIZADOR@IP_DO_SERVIDOR
```

Enquanto o SSH estiver aberto, visita `http://127.0.0.1:8787` (NOVA) ou `http://127.0.0.1:8096` (Jellyfin) **no computador a partir do qual abriste o túnel**.

### Diagnóstico rápido

```bash
curl --fail http://127.0.0.1:8787/api/v1/health/live
curl --fail http://127.0.0.1:8787/api/v1/status
# logs (podem conter metadados operacionais; não partilhar sem redigir):
docker compose logs --tail=40 nova-core
docker compose logs --tail=40 jellyfin
```

### Parar / actualizar

```bash
docker compose down                  # preserva diretórios persistentes
docker compose up -d --build         # reinicia após revisão das versões
```

**Não executar `docker compose down -v` nem eliminar `state/` sem cópias de segurança.** A recuperação cifrada offline e o procedimento de reversão já estão disponíveis no guia M2; não há atualização automática. O Core versiona o schema SQLite e recusa schemas futuros.

## Fronteiras de segurança desta prova

| Medida | Estado |
|---|---|
| Duas origens montadas read-only no Jellyfin | Aprovado em Docker Linux na CI: leitura e tentativa de escrita bloqueada |
| NOVA Core sem acesso direto aos filmes | Configurado em Compose |
| Portas 8096 e 8787 vinculadas a `127.0.0.1` | Configurado, exige validação real no host |
| Senha NOVA Argon2id + segredo de bootstrap | Implementado e testado em Python |
| Sessão opaca, token só em memória do browser, digest no SQLite | Implementado e testado em Python |
| Antiforça-bruta básico persistente em SQLite | Implementado, **não** substitui proteção de rede |
| Comunicação Docker interna NOVA↔Jellyfin | **HTTP em rede Docker local**; NÃO é E2EE nem TLS |
| Base SQLite de NOVA | Proteção de permissões; **não cifrada em repouso** |
| Autenticação de dispositivo TV, Directory e convites | **Não implementados** |
| NOVA Connect integrado, VPN externa, relay E2EE | **Não implementados** |
| Encriptação fim-a-fim filme/cliente | **Não implementada** |
| Auditoria de intrusão / OWASP | **Não executada** |

**Regra operacional:** apenas testar em laboratório/rede controlada. Nada de abrir portas, configurar DMZ ou convidar utilizadores remotos com esta versão. O painel local usa HTTP por estar vinculado a loopback ou a um túnel SSH já cifrado; não mudar a vinculação para `0.0.0.0` sem implementar TLS e segurança correspondente. O modelo em produção terá de oferecer transporte cifrado também na rede local.

## Estrutura

```text
compose.yaml                  pacote Jellyfin oficial + NOVA Core
Dockerfile                    imagem NOVA Core, sem root
nova_server/app.py            API local e painel de administração
nova_server/security.py       Argon2id, tokens aleatórios, comparação constante
nova_server/storage.py        dados SQLite, sessão e auditoria local
nova_server/jellyfin.py       diagnóstico não privilegiado Jellyfin
nova_server/static/           interface NOVA Control inicial
scripts/install.py            criação de .env, fontes e token inicial
scripts/first_run.py          bootstrap seguro do proprietário
state/                        criado durante instalação, NUNCA vai no ZIP

tests/                        testes locais de API, fontes, segurança, composição
```

## Executar testes locais

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
```

Os testes unitários usam `httpx.MockTransport` e FastAPI `TestClient`. O teste separado `scripts/smoke_compose.py` arranca contentores reais, configura Jellyfin via NOVA e exige dois vídeos sintéticos indexados, retoma sem bibliotecas duplicadas e persistência após reinício. Consultar o relatório M2 para o resultado da execução; reprodução e VPN continuam fora desta prova.

## Próximas entregas (não confundir com concluídas)

1. **P01.2:** Docker Linux, saúde Jellyfin e acesso read-only às duas origens aprovados na CI; wizard unificado e indexação das duas origens aprovados em Docker no incremento M2; executar testes TrueNAS Community e backup/restauro.
2. **P02:** NOVA Directory/Identity, convites, associação servidor-conta, autenticação segura via código no telemóvel (RFC 8628).
3. **P03:** NOVA Connect, canal autenticado e cifrado NOVA Cinema↔NOVA Server, WireGuard/Tailscale/NetBird nativos; testar relay que não pode desencriptar conteúdo.
4. **P04:** primeira APK NOVA Cinema real com login, descoberta automática de servidor, biblioteca Jellyfin e Media3 Direct Play.
5. **SEC:** testes das 12 barreiras de segurança, isolamento entre duas instalações, backup cifrado e auditoria externa antes de disponibilizar a familiares.

**Referências:** [Jellyfin — Docker e múltiplos volumes](https://jellyfin.org/docs/general/installation/container/), [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/), [OWASP MASVS](https://mas.owasp.org/MASVS/).

## Incremento M3 de laboratório

As fontes atuais incluem associação por código, aprovação/revogação no Control e API HTTPS separada. Consultar [M3](../docs/M3_ASSOCIACAO_DISPOSITIVOS.md). O serviço cliente exige ativação explícita e não é iniciado pelo Compose M2. O schema passa para 2: preservar backup para regressar à imagem M2.
