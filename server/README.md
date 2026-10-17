# NOVA Server — P01 v0.1.1 · base de laboratório

Atualização de 17-10-2026: login Control corrigido, diagnóstico Jellyfin limitado a 16 KiB/4 s com validação de produto/wizard/identidade opcional, limite de login atómico, duas verificações Argon2 simultâneas por processo, dependências transitivas fixadas com hashes. Cinco falhas/tentativas em curso por origem durante 15 minutos; sucesso retira apenas a própria reserva e não apaga outras falhas. A administração aceita Host `localhost`/`127.0.0.1`.

O Control guarda **rascunhos** WireGuard/Tailscale/NetBird sem segredos nem ativação de rede. As origens mostram permissões/leitura/indexação ainda não verificadas. Para comparar a identidade Jellyfin com uma associação aprovada, definir `NOVA_JELLYFIN_SERVER_ID` no ambiente do Core; sem isso o diagnóstico devolve `identity_verified=false`.

Testes e limitações atuais: [fase 1](../docs/FASE_1_RESULTADOS.md). O restante percurso de instalação abaixo continua destinado a laboratório; não foi executado neste TrueNAS.

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
3. Criar configuração, **sem utilizar root** (substituir pelos teus caminhos):

   ```bash
   python3 scripts/install.py --media-a "/mnt/disco1/Filmes" --media-b "/mnt/disco2/Series"
   ```

   O instalador valida caminhos, cria `.env` em modo `0600`, diretórios de dados locais e token temporário de primeira instalação (`state/nova/bootstrap.token`, também `0600`). Recusa substituição acidental da configuração existente.

4. Arrancar os serviços:

   ```bash
   docker compose up -d --build
   docker compose ps
   ```

5. Configurar o proprietário no terminal do **próprio servidor**:

   ```bash
   python3 scripts/first_run.py
   ```

   Define o nome de proprietário e uma palavra-passe longa. O token de bootstrap é invalidado e apagado da pasta de dados após utilização.

6. Abrir o painel local `http://127.0.0.1:8787` e entrar com as credenciais NOVA; ver o estado do Jellyfin.

7. **Primeiro arranque do Jellyfin:** abrir `http://127.0.0.1:8096` (localmente ou com túnel SSH) e completar o **assistente inicial do próprio Jellyfin**. Adicionar `/media/source-a` e `/media/source-b` às bibliotecas pretendidas. Se quiseres filmes e séries separados, cria bibliotecas diferentes; se quiseres um só catálogo de filmes a partir dos dois diretórios, adiciona ambos à biblioteca correspondente. Não confundir conta Jellyfin com o proprietário NOVA desta prova.

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

**Não executar `docker compose down -v` nem eliminar `state/` sem cópias de segurança.** Em futuras versões o instalador deverá gerir migrações e backups cifrados.

## Fronteiras de segurança desta prova

| Medida | Estado |
|---|---|
| Duas origens montadas read-only no Jellyfin | Configurado em Compose; não testado em Docker real |
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

Os testes usam `httpx.MockTransport` e FastAPI `TestClient`; **não testam contentores, login Jellyfin, reprodução de vídeo ou VPN real**.

## Próximas entregas (não confundir com concluídas)

1. **P01.2:** verificar Docker real, saúde da imagem Jellyfin e acesso a ambos os diretórios; desenhar wizard unificado de Jellyfin + NOVA e testes TrueNAS SCALE.
2. **P02:** NOVA Directory/Identity, convites, associação servidor-conta, autenticação segura via código no telemóvel (RFC 8628).
3. **P03:** NOVA Connect, canal autenticado e cifrado NOVA Cinema↔NOVA Server, WireGuard/Tailscale/NetBird nativos; testar relay que não pode desencriptar conteúdo.
4. **P04:** primeira APK NOVA Cinema real com login, descoberta automática de servidor, biblioteca Jellyfin e Media3 Direct Play.
5. **SEC:** testes das 12 barreiras de segurança, isolamento entre duas instalações, backup cifrado e auditoria externa antes de disponibilizar a familiares.

**Referências:** [Jellyfin — Docker e múltiplos volumes](https://jellyfin.org/docs/general/installation/container/), [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/), [OWASP MASVS](https://mas.owasp.org/MASVS/).
