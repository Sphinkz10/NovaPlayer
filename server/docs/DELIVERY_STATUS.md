# NOVA Server — P01 v0.1 · Relatório de entrega

## Implementado
- Compose com `jellyfin/jellyfin:12.2.20261005-225228` e NOVA Core FastAPI; 2 diretórios de media em volumes read-only; mapeamento de portas apenas em loopback.
- Instalador e bootstrap inicial não root, que não reutiliza nem substitui segredos antigos.
- Painel NOVA Control local, API de estado, autenticação do proprietário com Argon2id e tokens temporários com revogação.
- Verificação do endpoint público de saúde Jellyfin e estados `ready`, `setup_required`, `offline`, `timeout`, `unauthorized`, `unexpected` e `invalid_response`.
- Testes unitários/integração HTTP em memória e verificações estáticas da composição.

## Não implementado / não validado
- Sem Docker Engine no ambiente de desenvolvimento: imagens/Compose não iniciadas nem testadas em execução.
- Não foi instalado nem configurado no NAS/TrueNAS; nenhum diretório real foi acedido.
- Jellyfin tem wizard inicial independente na versão P01; unificação pendente.
- Jellyfin usa HTTP em bridge Docker; não satisfaz o requisito completo de encriptação em trânsito.
- Nenhuma APK, NOVA Directory/Identity, VPN, autenticação de utilizador final, streaming E2EE, trailers ou Smart.
- Sem ciframento de volume/DB, MFA ou pen test; sem certificação de segurança.

## Roadmap de gates
| Gate | Objetivo | Estado |
|---|---|---|
| P01-A | Projeto NOVA Server distribuível e testes locais | Implementado, a validar em Docker |
| P01-B | Docker real + wizard integrado + suporte TrueNAS | Pendente |
| P02 | Directory, login e convites | Pendente |
| P03 | Ligação privada automática e E2EE | Pendente |
| P04 | APK NOVA Cinema e Media3 | Pendente |
| SEC-01…12 | Auditoria de segurança e prova em rede real | 0/12 |
