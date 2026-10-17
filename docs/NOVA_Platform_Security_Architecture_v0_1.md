# NOVA Platform — Security Architecture v0.1
**Data:** 2026-10-14 · **Estado:** requisitos vinculativos propostos; implementação e testes de segurança ainda não realizados.

## Âmbito e fronteiras
**NOVA Server** é instalado por cada proprietário e gere Jellyfin, NOVA Core/API, contas, pastas, NOVA Connect, dados de Smart/Planner e chaves. **NOVA Cinema** é o cliente, com login e descoberta automática. **NOVA Directory/Identity** é um serviço de associação de identidades a servidores, não um repositório nem um proxy que deva ler media. **NOVA Relay/Edge** é opcional e apenas deve transportar conteúdos cifrados entre os extremos.

Não assumir que VPN equivale a autenticação do utilizador; não assumir que família equivale a confiança; não assumir que o NAS/host está imune a comprometimento. Um servidor proprietário comprometido pode ler os ficheiros aos quais tem acesso; a encriptação em trânsito não resolve isso. O Directory necessita de certos metadados de associação e de disponibilidade, mesmo sem guardar títulos ou media.

## Objetivos obrigatórios
- **S-01 — Trânsito:** toda a API, autenticação, metadados privados e streaming remoto são cifrados e autenticados de extremo a extremo entre **NOVA Cinema e NOVA Server do proprietário**, com TLS 1.3 como alvo e configuração controlada para compatibilidade. Sem fallback silencioso para HTTP público; a ligação local também exige autenticação e transporte protegido ou uma justificação formal e isolamento estrito (recomendação: TLS também na LAN).
- **S-02 — Intermediários:** Directory e relays não terminam a proteção criptográfica que contém o vídeo, tokens de media ou histórico. Se for necessária terminação TLS externa para metadados de controlo, esses dados são segregados do fluxo cifrado de media. Relay sem armazenamento de media por defeito. Registar apenas métricas operacionais mínimas, nunca URLs com tokens.
- **S-03 — Conectividade:** o admin escolhe NOVA Connect integrado, VPN externa suportada ou Edge outbound. As rotas do cliente alcançam só o serviço NOVA atribuído, nunca a rede inteira, TrueNAS UI, SMB, SSH nem serviços de outras instâncias. Uma VPN não elimina as verificações de autenticação e autorização na NOVA Core e no Jellyfin.
- **S-04 — Identidades e sessão:** login de televisão preferencialmente através de fluxo de autorização por dispositivo conforme RFC 8628; aprovação num telemóvel e sessão ligada a TV/dispositivo/conta/servidor. Sessões curtas, refresh rotativo, revogação remota, rate limiting e deteção de uso suspeito. MFA/passkeys para proprietários; credenciais nunca guardadas em texto simples. Passwords armazenadas como **hash Argon2id com sal individual**, não 'encriptadas' de forma reversível.
- **S-05 — Segredos cliente:** chaves e tokens num armazenamento protegido por Android Keystore quando suportado; chaves hardware-backed quando o dispositivo suportar; sem chaves administrativas nem endereços secretos embutidos no APK, nem em screenshots/logs. Perda de Keystore exige novo emparelhamento, nunca desativar proteção.
- **S-06 — Segredos servidor:** chaves por servidor e por dispositivo; rotação e revogação; armazenamento de segredos fora de imagens Docker, repositórios, logs e envs públicas; permissões mínimas e APIs de gestão separadas da API de cliente. Mecanismo seguro de recuperação e substituição das chaves de cada instância.
- **S-07 — Em repouso:** dados sensíveis NOVA cifrados em volumes/BD onde apropriado; TrueNAS/ZFS cifrado por opção compatível com o hardware (avaliar a gestão de chaves e o desbloqueio após arranque). Backups cifrados e restaurados em testes. O ciframento do volume não dispensa autorização no processo. Os ficheiros de media podem manter-se descodificáveis pelo Jellyfin do proprietário, pois o player necessita de os servir.
- **S-08 — Multi-tenancy:** utilizador/dispositivo com associação explícita a um ou mais NOVA Servers; contexto da instância verificado em TODAS as queries/APIs, convites, pedidos, notificações e media. IDs imprevisíveis e sem confiar em IDs enviados pelo cliente. Testar ataques de IDOR/BOLA e movimentos laterais entre duas instâncias reais.
- **S-09 — Atualizações:** imagens/artefactos fixados por versão, originados de fontes de confiança, atualizações autenticadas, análise de dependências, SBOM e plano de correções. Jellyfin atualizado de forma independente do NOVA Core; sem modificações não auditadas do seu código criptográfico.
- **S-10 — Privacidade:** Directory armazena apenas associação conta/servidor e metadados estritamente necessários; media e histórico permanecem no NOVA Server por defeito. Telemetria opt-in quando identificar utilizadores. Não enviar dados de visualização a serviços de recomendação externos por defeito.
- **S-11 — Resiliência e incidentes:** backups, recuperação de administração, bloqueio de contas/dispositivos, validade e rotação de certificados, verificação de integridade, alarmes e logs mínimos. Falhar fechado em erro de certificado, servidor não reconhecido ou permissão.
- **S-12 — Criptografia:** bibliotecas auditadas, nunca inventar protocolos/algoritmos. AES-GCM/ChaCha20-Poly1305 ou primitivas dos protocolos certificados; aleatoriedade criptográfica do sistema, gerenciamento de nonces, proteção de replay e atualização de algoritmos/chaves.

## Matriz de fronteiras de confiança
| Ligação | Controle proposto | O que o intermediário vê |
|---|---|---|
| NOVA Cinema ↔ NOVA Directory | HTTPS TLS 1.3, login limitado e código de TV de uso curto | Identidade e associação necessárias; **não** o catálogo privado e o vídeo |
| NOVA Cinema ↔ NOVA Server direto | TLS fim-a-fim, identidade do servidor fixada/validada, autorização por conteúdo | Provedor de rede observa metadados de tráfego, não o vídeo |
| NOVA Cinema ↔ Relay ↔ NOVA Server | Túnel cifrado fim-a-fim **sem terminação de media no Relay** | Relay observa rota, tamanhos e horários; **não** payload de vídeo |
| NOVA Server ↔ Jellyfin local | Rede interna isolada, autorização, segredos restritos; TLS quando adequado | Administrador do próprio host pode ler dados acessíveis ao Jellyfin |
| Backups e armazenamento NOVA | Ciframento de volume/dados, gestão de chaves e restore testado | Operador do backup não lê dados sem chaves; proprietário com chaves pode ler |

## Modos VPN — limitação explícita
1. **NOVA Connect por túnel de aplicação** (alvo principal): a NOVA Cinema estabelece canal cifrado do seu próprio processo; pode evitar diálogo de permissão VPN do Android se não usar `VpnService`. O transporte e comportamento com NAT/relay exigem prova técnica.
2. **NOVA Connect via `VpnService`/WireGuard:** fornece VPN do sistema, mas o Android normalmente exige consentimento inicial e só admite uma VPN ativa por utilizador. Com chaves únicas por dispositivo e split tunnel restrito.
3. **VPN externa suportada pelo NOVA Server:** admin configura UniFi/WireGuard/Tailscale conforme adaptador; não se promete integração transparente com qualquer fornecedor até demonstração técnica.
4. **NOVA Edge outbound:** o servidor doméstico inicia ligação de saída sem encaminhamento de portas para NAS. Relay só transporta dados cifrados; custos de largura de banda e performance medidos antes de disponibilizar.

## Critérios de aceitação — gate pré-convite
- **SEC-01:** captura de tráfego LAN/remoto e relay confirma ausência de media/tokens/passwords em texto simples.
- **SEC-02:** relay comprometido/teste com operador malicioso não permite reproduzir media ou emitir tokens de Jellyfin.
- **SEC-03:** cliente com certificado ou identidade de servidor alterados bloqueia ligação (sem downgrade).
- **SEC-04:** cliente A não entra em NOVA Server B sem convite; brute forcing de IDs não altera isso.
- **SEC-05:** cliente familiar não acessa TrueNAS UI, SSH, SMB, outros hosts/VLANs nem a API administrativa.
- **SEC-06:** duas contas autorizadas com bibliotecas distintas não veem conteúdos ou histórico uma da outra.
- **SEC-07:** revogar um dispositivo ou convite termina novas sessões e invalida credenciais dentro do SLA definido.
- **SEC-08:** perda/roubo de TV; logout remoto; tokens não recuperáveis de backups comuns nem de logs.
- **SEC-09:** recuperação após reboot/queda de rede mantém a política segura; não faz fallback para HTTP nem para servidor desconhecido.
- **SEC-10:** backup cifrado restaura e recupera as contas sem copiar chaves para ficheiros inseguros.
- **SEC-11:** SAST, SCA/SBOM, verificação de dependências e revisão de implementações criptográficas; auditoria manual de autenticação/autorização.
- **SEC-12:** verificação OWASP MASVS (cliente) + OWASP ASVS (Directory/NOVA Server); testes de intrusão independentes antes de distribuição pública.

## Decisões técnicas ainda em aberto
- Alojamento e controlo operacional do Directory; definir divulgação e recolha mínima de metadados.
- P2P/NAT traversal: TURN/relay, sem prometer P2P universal nem 4K por relay; monitorizar custos.
- Terminação TLS end-to-end, rotatividade de certificados e pinning seguro com recuperação em troca de certificado.
- Modelo de contas (centralizadas, federadas, ou combinação) e política multi-servidor; não criar dependência desnecessária do Directory para reprodução local depois da associação.
- Compatibilidade de instalações em TrueNAS SCALE, Docker e outros sistemas, isolamento de container e redes.
- Política de ciframento do armazenamento de media e desbloqueio do servidor após reboot sem perder segurança.

## Estado verdadeiro
Esta é uma **especificação**. Nem este texto, nem os diagramas, nem os 131 testes locais de lógica anteriores comprovam encriptação fim-a-fim, isolamento de rede, segurança do Directory, qualidade da APK ou segurança do NAS. Todas as provas SEC estão **por executar**.

## Referências de implementação
- OWASP MASVS: https://mas.owasp.org/MASVS/
- OWASP ASVS: https://owasp.org/www-project-application-security-verification-standard/
- TLS 1.3: https://www.rfc-editor.org/rfc/rfc8446
- OAuth Device Authorization RFC 8628: https://www.rfc-editor.org/rfc/rfc8628
- OWASP Password Storage: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- Android Keystore: https://developer.android.com/privacy-and-security/keystore
