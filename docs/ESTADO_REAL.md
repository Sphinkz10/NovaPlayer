# Estado real — NOVA Platform (18-10-2026, início M3)

A base está em desenvolvimento. O servidor local e a APK de diagnóstico compilam;
a jornada instalar → associar → biblioteca → vídeo ainda não existe.

| Componente | Estado atual | Próxima prova |
|---|---|---|
| NOVA Server 0.2.0-lab | Assistente, bibliotecas, gerador Apps, healthchecks, schema versionado e recuperação cifrada; Docker aprovou origem ausente e restauro com revogação | Aceitação física TrueNAS: instalação, ACL, reboot, atualização/restauro |
| Configuração Connect | Rascunhos autenticados de WireGuard/Tailscale/NetBird no Control e SQLite | Inscrição, agentes e aplicação da configuração real |
| NOVA Connect 0.5-pairing-lab | 198 testes Kotlin; cliente de associação na APK normal; os três motores compilaram numa APK experimental e carregaram em processos separados em API 26/35 x86_64 | Prova Android de associação; pontes funcionais VPN, handshake e HTTPS pelos túneis; ARM/TV físicos |
| NOVA Cinema | Designs e políticas de reprodução corrigidas | UI TV, biblioteca Jellyfin e player Media3 |
| Identidade/dispositivos M3 | Servidor e cliente Android de laboratório: associação, confirmação de identidade importada, Keystore, refresh e revogação | Prova emuladores/hardware; Directory, renovação TLS integrada e permissões Jellyfin |
| Directory | Contratos documentados; serviço ainda não implementado | Contas, registo com prova de posse e descoberta autenticada |
| CI | Linux/Windows, HTTP, navegador, Docker, Android e runtime nativo em emulador aprovados | Ligação real dos três fornecedores e execução em hardware; ver relatório |
| Segurança | Correções locais verificadas e análise Python sem avisos conhecidos | SEC-01…12 continuam sem validação final |

Alvos: TrueNAS Community e vários Android TV/Google TV. Xiaomi Box S2 e Chromecast
Android TV são aparelhos iniciais de aceitação, sem restrição da aplicação a essas
marcas. Android API 26+ e ABIs disponíveis são requisitos técnicos; não garantem
codec, HDR, 4K ou desempenho sem medição.

O proprietário configura o NOVA Server. O familiar deverá instalar só NOVA Cinema
e associar a conta/dispositivo, sem introduzir IPs ou perfis VPN. Apps VPN externas
não satisfazem o requisito de integração nativa dos três fornecedores.

Incremento atual: [M3_CLIENTE_ANDROID.md](M3_CLIENTE_ANDROID.md) e [servidor M3](M3_ASSOCIACAO_DISPOSITIVOS.md). Entrega M2: [M2_SERVIDOR_LAB.md](M2_SERVIDOR_LAB.md). Histórico: [FASE_1_RESULTADOS.md](FASE_1_RESULTADOS.md).
Decisões: [ADR_001_CONNECT_NATIVO.md](ADR_001_CONNECT_NATIVO.md).
Etapas de instalação: [roadmap](ROADMAP_INSTALACAO_SERVER_TV_v0_2.md).
