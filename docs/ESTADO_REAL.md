# Estado real — NOVA Platform (17-10-2026, fase 1)

A base está em desenvolvimento. O servidor local e a APK de diagnóstico compilam;
a jornada instalar → associar → biblioteca → vídeo ainda não existe.

| Componente | Estado atual | Próxima prova |
|---|---|---|
| NOVA Server 0.1.1 | Login Control corrigido, Argon2id/sessões, concorrência protegida, diagnóstico estrito, dependências com hashes | TrueNAS real, wizard e bibliotecas; Docker Linux já aprovado |
| Configuração Connect | Rascunhos autenticados de WireGuard/Tailscale/NetBird no Control e SQLite | Inscrição, agentes e aplicação da configuração real |
| NOVA Connect 0.4-phase1 | APK debug, WireGuard AAR, contratos de fornecedor, deteção SDK/ABI/Leanback; 166 testes Kotlin | Motores Tailscale/NetBird, associação, handshake e HTTPS reais |
| NOVA Cinema | Designs e políticas de reprodução corrigidas | UI TV, biblioteca Jellyfin e player Media3 |
| Directory/Identity | Contratos documentados | Serviço, contas, descoberta e dispositivos |
| CI | Linux/Windows, HTTP, navegador, Docker e Android aprovados na mesma revisão | Prova nativa Tailscale/NetBird e execução em hardware; ver resultados ligados no relatório |
| Segurança | Correções locais verificadas e análise Python sem avisos conhecidos | SEC-01…12 continuam sem validação final |

Alvos: TrueNAS Community e vários Android TV/Google TV. Xiaomi Box S2 e Chromecast
Android TV são aparelhos iniciais de aceitação, sem restrição da aplicação a essas
marcas. Android API 26+ e ABIs disponíveis são requisitos técnicos; não garantem
codec, HDR, 4K ou desempenho sem medição.

O proprietário configura o NOVA Server. O familiar deverá instalar só NOVA Cinema
e associar a conta/dispositivo, sem introduzir IPs ou perfis VPN. Apps VPN externas
não satisfazem o requisito de integração nativa dos três fornecedores.

Resultados detalhados: [FASE_1_RESULTADOS.md](FASE_1_RESULTADOS.md).
Decisões: [ADR_001_CONNECT_NATIVO.md](ADR_001_CONNECT_NATIVO.md).
Etapas de instalação: [roadmap](ROADMAP_INSTALACAO_SERVER_TV_v0_2.md).
