# Estado real — NOVA Platform (17-10-2026)

## Visão correta do produto

**NOVA Server:** pacote instalável no servidor de cada proprietário, contendo Jellyfin + NOVA Core e, futuramente, NOVA Connect, NOVA Control, gestão de bibliotecas, usuários, contas, pedidos e planeamento. Instalação pretendida no TrueNAS SCALE ou Linux com Docker. Dois ou mais diretórios.

**NOVA Cinema:** aplicação Android TV destinada aos convidados, com interface Premium, login, descoberta automática do servidor e reprodução Jellyfin. Não tem de configurar IP nem VPN.

**NOVA Directory:** infraestrutura proposta para login e ligação conta ↔ NOVA Server, com descoberta automática. Por implementar; não guarda media.

**NOVA Connect:** comunicação segura integrada; modos direto, VPN externa controlada pelo admin e alternativa edge/relay. O relay não deve ter chaves para descodificar vídeos. Por implementar na arquitetura final.

## Componentes efetivamente disponíveis

| Componente | Estado demonstrado | Falta |
|---|---|---|
| Figma Premium 1080p/720p | Design e protótipos editáveis no Figma remoto | UI Android real e exportação `.fig` offline |
| Documento G0, F00, F01, Security | Ficheiros Markdown originais | Revisão e atualização final para arquitetura multi-proprietário |
| NOVA Server P01 v0.1 | Código FastAPI, Docker Compose com Jellyfin, README, testes Python | Validação Docker/TrueNAS, configuração unificada, segurança produção |
| NOVA Connect PoC v0.3 | Android Kotlin PoC e testes JVM conforme documentação original | APK compilada, handshake real, associação, permissão e isolamento reais |
| NOVA Directory/Identity | Planeado / documentado no Figma | Implementação completa |
| NOVA Cinema APK | Protótipos Figma | Código funcional, builds, instalação, testes TV |
| Plataforma multi-servidor | Arquitetura corrigida no Figma | Dois servidores a funcionar em teste, auto-discovery |
| Segurança P2P/E2EE | Requisitos e gates documentados | Implementação e auditoria de terceiros; 0/12 verificações finais |

Não existe aqui uma APK final, nem um pacote NOVA Server produção pronto, nem um ficheiro `.fig` exportado. Os resultados de testes anteriores estão documentados nas respetivas versões de origem, não foram novamente executados para gerar este arquivo.

## Segurança e confidencialidade

Não colocar na Internet o protótipo do NOVA Server nem abrir as portas 8096/8787 do NAS. Não reutilizar diretamente o protótipo da VPN como configuração de produção. Não incluir credenciais reais, chaves de família, tokens nem `.env` gerado nos arquivos de partilha.
