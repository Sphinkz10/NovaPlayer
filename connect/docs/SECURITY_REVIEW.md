# Revisão de segurança v0.3 — prova, não auditoria de produção

## Limites do ambiente

A NOVA POC ainda NÃO foi compilada no Android, não abriu um WireGuard real e não contactou o TrueNAS/Jellyfin do utilizador. Os testes locais executam apenas lógica JVM e um mock HTTP. Ausência de segredos na fonte **não prova** segurança em tempo de execução.

## Controlo pretendido

| Ameaça | Medida no protótipo | Falta provar |
|---|---|---|
| Convidado aceder ao NAS | Tráfego VPN restrito à app NOVA e IP /32 aprovado | Firewall do gateway e testes a TrueNAS, SMB e SSH |
| Fallback inesperado para Internet pública | LAN/VPN aceitam endpoint numérico privado e HTTPS; sem fallback | Teste real de DNS e proxy, rotas e TLS no Android |
| Certificado HTTPS inválido | `TLS_VALIDATION_FAILED`, sem retry cego e sem TrustManager inseguro | TLS com CA/certificado real, certificado IP SAN ou nome privado |
| Outro servidor Jellyfin responder | ID de servidor esperado num perfil cifrado e verificado no probe | Canal de provisionamento autenticado e descoberta inicial segura |
| Roubo de configuração VPN | AES-GCM com Android Keystore e AAD, backups Android desligados | Teste da chave após reinstall, armazenamento em memória e rotação |
| Chave/convite comprometidos | Sem chaves estáticas no APK; perfis por dispositivo planeados | Provisionamento real, TTL, aprovação e revogação remota |
| Uso de vídeo não autorizado | Política depende da conta e biblioteca; Direct Play prioritário | Aplicar verificação à API e ao Media3 real |
| DDoS e streaming excessivo | Probe com timeout e tamanho máximo; políticas básicas | Limites reais da API, sessões simultâneas, jitter e backoff |
| Conflito Android VPN | `VpnService.prepare`, sem bypass silencioso | Testes Android VPN existente / troca de redes / revogação |

## Regras de aceitação

- O servidor VPN pode estar acessível por uma porta UDP na **UDR** no modo WireGuard; não é uma porta de entrada direta para o serviço NAS.
- Conta de familiar vê apenas biblioteca autorizada. Não conhece token admin nem tem acesso à LAN.
- Não descarregar segredos em tickets, chats, logs, backups ou screenshots.
- A interface apenas usa vídeo transcoded mediante autorização explícita conforme política. Não há reprodução automática neste POC.
- `VpnService` por app não basta para proteger o NAS; é indispensável segmentação de rede, firewall e teste negativo.
- HTTPS validado, sem fallback para HTTP, certificado ausente ou proxy público não autorizado.
- `LAN_VERIFIED` continua a ser um **sinal de um verificador ainda por implementar**. Testá-lo como bool de entrada não é validação da rede real.
- O túnel iniciado pela app não cobre outros apps (por exemplo, leitor externo de trailers); o produto terá de arquitetar o tráfego de metadados/trailers separadamente.

## Risco ainda crítico

**Não usar este projeto em produção.** Falta autenticação de utilizadores Jellyfin, aprovação de dispositivos, modelo de hostname/certificados, backend de invites, builds Android, conectividade real, persistência segura dos tokens de media, monitorização e simulações de ataque. A POC não implementa a experiência de familiares completa.
