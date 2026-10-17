# NOVA — Primeira entrega de implementação após auditoria

17-10-2026 · Server 0.1.1 · Connect laboratório 0.4-phase1

**Entrega local:** estabilização da base e preparação de configuração dos três fornecedores.
**M0 ainda aberto:** falta incorporar e provar Tailscale/NetBird e demonstrar HTTPS real por
cada motor. **M1 com validação local concluída, gates Linux/CI pendentes.** Não é ainda
o pacote instalável de produção nem a NOVA Cinema com reprodução.

## Código entregue

1. O formulário Control guarda a referência ao formulário antes dos `await`; login
   real abre o painel e limpa a palavra-passe, mantendo o token só em memória.
2. Saúde Jellyfin valida produto, ID, tipo booleano do wizard e identidade esperada
   quando configurada. Limites de 16 KiB e quatro segundos totais; recusa redirecionamentos,
   compressão e respostas inválidas. Estado ready não prova biblioteca/reprodução.
3. O overview passa a distinguir origem configurada de leitura, indexação e read-only
   observados. Os três estados observados são desconhecidos até à prova de montagem.
4. Tentativas de login reservadas atomicamente em SQLite, antes de Argon2. O teste de
   12 pedidos simultâneos obtém cinco 401 e sete 429. Outra prova usa 12 instâncias de
   Store sobre a mesma base. Sucesso só retira a sua reserva; limite de duas operações
   Argon2 em simultâneo por processo. Conexões SQLite são fechadas explicitamente.
5. Host administrativo limitado a localhost/127.0.0.1. FastAPI 0.143.3 e Starlette 1.8.0
   compatíveis; resolução transitiva fixada com hashes para runtime e testes.
6. NOVA Control permite guardar rascunhos WireGuard, Tailscale e NetBird. API exige sessão,
   valida campos próprios por fornecedor, recusa chaves/campos desconhecidos, persiste
   configurações e regista eventos sem os valores. Não inscreve peers nem altera redes.
7. Android passa a consultar API/ABIs/Leanback, sem lista de fabricantes/modelos. Contratos
   comuns distinguem engine ausente, dispositivo incompatível, consentimento, túnel,
   verificação do serviço e revogação. Não há troca automática de fornecedor.
8. Política de reprodução distingue contentor/remux, conversão de áudio, codec de vídeo
   e legendas. Manifest TV dispensa touch/faketouch obrigatórios, inclui ícone/banner e
   exclusões de cópia/transferência de dados Android. Ainda não existe player.
9. Gradle Wrapper 8.11.1 verificado contra SHA256 oficial, locks e verificação SHA256 dos
   artefactos Maven, incluindo AAPT Windows/Linux/macOS. Build de verificação repetido
   sem regenerar checksums. Adicionado módulo Gradle para testes Kotlin com a mesma
   versão de compilador da APK.
10. Workflows Linux/Windows Python 3.12/3.13, navegador, análise de dependências, Android
    e Docker de laboratório. Gate Compose usa projeto temporário, duas origens descartáveis,
    arranque HTTP, tentativa de escrita bloqueada, restart e persistência. Não foi executado
    aqui. Inventários e documentação corrigidos; manifests históricos preservados em archives.

## Evidências executadas nesta máquina

| Verificação | Resultado | Limite |
|---|---|---|
| Python / pytest | **88 aprovados, 4 ignorados** | Windows, Python 3.12.14; os quatro testes exigem Linux real |
| HTTP NOVA Core | **Aprovado** | Bootstrap, login, overview, Jellyfin desligado em loopback |
| Navegador Edge real | **Aprovado** | Login inválido/válido, painel, limpeza do formulário, três rascunhos persistidos, logout, zero erros JS |
| Kotlin via Gradle | **165 aprovados** | 116 políticas + 19 HTTP simulado + 30 fornecedor/compatibilidade |
| APK assembleDebug | **Aprovado** | Windows, JDK 17, SDK 35, AGP 8.9.2, Kotlin 2.0.21 |
| Android lint | **0 erros, 10 avisos** | Avisos de strings de diagnóstico, tamanho de vetor e persistência síncrona |
| Assinatura APK | **Debug v2 verificada** | Sem chave de distribuição definitiva |
| ABIs na APK | **arm64-v8a, armeabi-v7a, x86, x86_64** | Bibliotecas WireGuard; não comprova funcionamento em todas as TVs |
| Alinhamento ZIP APK | **zipalign -P 16 aprovado** | Não equivale a provar execução em dispositivo de páginas 16 KiB |
| Análise Python | **Nenhuma vulnerabilidade conhecida encontrada** | Dependências runtime fixadas; não cobre imagem Linux nem bibliotecas Android |
| Verificações heurísticas Connect | **11/11** | Não substituem revisão de segurança |

Há um aviso de depreciação do TestClient Starlette com httpx na suíte Python. Não houve
falhas de teste por esse aviso. A CI foi escrita, mas não executada/publicada no GitHub
nesta entrega. As alterações estão locais na branch `codex/phase-one`, baseada no commit
`57391fcc64e9e65220d6ed59f02dfa98f052db38`.

## Artefactos

- `NOVA_Connect_Lab_v0.4-phase1-debug.apk`: package `com.novacinema.connect.poc`,
  versionCode 4, Android mínimo API 26, target 35. É diagnóstico, sem login familiar,
  biblioteca ou reprodução.
- SHA256 da APK: `1751db3d5a979f6920e012cb5b1b9b2c3c09e909847a1c56e6e0698fc87ee348`.
- ZIP de fontes da fase 1, com inventário SHA256; sem `.env`, estado, perfis, caches,
  credenciais ou ambientes virtuais.
- Logs, resultado de navegador, captura Control, análise de dependências e SBOM Python
  guardados com a entrega local. O SBOM não cobre ainda o conjunto Android/containers.

## O que esta entrega não demonstrou

Não foram iniciados contentores: Docker/WSL não estão disponíveis aqui. Não houve acesso
ao TrueNAS, instalação em Xiaomi/Chromecast, handshake, pedido HTTPS por uma VPN real,
inscrição Tailscale/NetBird, biblioteca, filme ou validação de firewall. **SEC-01…12
continuam por executar.** A base genérica não exige novos modelos de TV para prosseguir.

As fontes oficiais Tailscale/NetBird foram inspecionadas e fixadas para investigação no
[ADR 001](ADR_001_CONNECT_NATIVO.md). Compilar os respetivos AARs e provar coexistência
na mesma APK exige preparar a toolchain Go/NDK e implementar as pontes; as contas e
os dois extremos de teste serão necessários para a prova de conectividade. Nenhum stub
é apresentado como VPN funcional.

Próxima sequência: terminar a prova dos três motores em M0, executar gates Linux/Docker
de M1 e concluir arranque/wizard/bibliotecas do servidor em M2. A reprodução local na TV
continua em M4, e suporte remoto integral aos três fornecedores em M5/M6.
