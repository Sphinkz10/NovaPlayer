# ADR 001 — Base comum para três fornecedores nativos

Estado: contrato inicial e compilação conjunta dos três motores aprovados; pontes funcionais e provas de rede pendentes.
Data: 17-10-2026. Substitui a interpretação de que uma app VPN externa satisfaz NOVA Connect.

## Compatibilidade

NOVA destina-se a vários Android TV/Google TV e boxes compatíveis, sem lista de marcas
permitidas. A base Android exige API 26 ou superior. O motor WireGuard incluído contém
armeabi-v7a, arm64-v8a, x86 e x86_64; a aplicação consulta o SDK, ABIs e Leanback do
equipamento. Isto verifica requisitos de instalação, não codecs, vídeo, VPN ou desempenho.
Xiaomi Box S2 e Chromecast Android TV são os primeiros aparelhos de aceitação; não são
os únicos permitidos. Capacidades de reprodução serão obtidas no dispositivo em M4.

O servidor continua dirigido a Linux/Docker e TrueNAS Community. Escolher o mecanismo
de instalação conforme a versão existente no NAS durante M2, sem alterar o seu sistema base.

## Contratos implementados

- Identificadores estáveis: `wireguard`, `tailscale`, `netbird`.
- API administrativa autenticada: `GET /api/v1/admin/connect` e
  `PUT /api/v1/admin/connect/draft`, versão de esquema 1.
- Rascunhos por fornecedor persistidos no SQLite. Sem chaves, passwords, comandos,
  tokens de API ou opções de ativação; campos desconhecidos são recusados.
- WireGuard: modo de gateway, endereço/porta UDP e origem privada HTTPS NOVA.
- Tailscale: tailnet e origem privada HTTPS NOVA.
- NetBird: origem de gestão HTTPS e origem privada HTTPS NOVA.
- Nenhum pedido aos fornecedores é feito ao guardar. Não se alteram rotas nem serviços.
  `active_provider=null` e `remote_access_enabled=false` continuam explícitos.
- `ProviderRegistry` Android avalia o fornecedor pedido, SDK e ABI. Não substitui um
  motor ausente por outro. `NativeProviderEngine` é a primeira fronteira de diagnóstico
  e desligamento; o adaptador WireGuard existente implementa-a.
- Estado `CONNECTED` exige evidências de túnel, HTTPS privado, identidade do servidor
  e autorização do dispositivo. Túnel UP isoladamente fica em verificação. Esta política
  tem testes de domínio; a coleta dessas evidências na jornada de produto permanece pendente.
- Revogação prevalece sobre todos os estados. O catálogo distingue uma biblioteca
  compilada de integração completa. Tailscale e NetBird são `NOT_IMPLEMENTED`.

## Fronteiras a preservar na implementação dos motores

O proprietário autoriza o fornecedor no Control. Cada TV terá identidade e inscrição
próprias, recebidas por associação autenticada, com segredos no Android Keystore.
Credenciais administrativas ficam no servidor. O Directory recebe descoberta/identidade,
não segredos dos fornecedores ou media. O adaptador não recebe acesso livre ao socket
Docker nem um comando shell fornecido por HTTP.

Só um fornecedor fica ativo por vez. A troca terá de desligar o anterior, cancelar
callbacks pendentes e obter nova evidência de identidade/autorização. Não abrir fallback
público nem ultrapassar o consentimento VPN do Android. Rotas /32 não substituem firewall
por porta: o acesso da TV deve terminar num serviço NOVA dedicado, sem abrir o NAS/LAN.

TLS termina no NOVA Server do proprietário. Relays transportam dados cifrados; não
recebem chaves de media. A API administrativa e o gateway de media autorizado devem
ter fronteiras separadas. O HTTP local existente serve apenas a administração de laboratório.

## Inspeção das fontes dos motores

| Motor | Fonte fixada para a investigação | Resultado nesta fase |
|---|---|---|
| WireGuard | `com.wireguard.android:tunnel:1.0.20260102` | AAR oficial incluído; build e quatro ABIs verificados; handshake pendente |
| Tailscale | `tailscale/tailscale-android@264102cc702fbd844e900227ee02e5cbb4d7f801` | Pacote libtailscale compilado no AAR conjunto e incluído na APK NOVA experimental |
| NetBird | `netbirdio/netbird@01185ba3536bcc037481578420d73cb7cee96094` | Pacote client/android compilado no mesmo AAR; fonte Go fixada pelo cliente Android consultado |

A [prova de compilação](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39069358627)
passou num runner Linux com Go 1.27.1, NDK 23.1.7779620 e API mínima 26.
Um único comando gomobile gera bindings para os dois pacotes, evitando duplicar
go.Seq/libgojni.so. Não foi usado pickFirst. A APK experimental inclui esse AAR e
WireGuard; ARM64, ARMv7 e x86_64 são as ABIs do AAR conjunto. A variante normal
continua apenas com WireGuard e não ativa Tailscale/NetBird.

O workflow preserva go.mod dos dois projetos, go.work/go.work.sum, módulos
resolvidos, licenças de topo e SHA256. O gerador mobile é fixado em
v0.0.0-20260816165457-f98cc9b3c733. A licença do wrapper Android NetBird não é
usada como substituto da revisão das licenças do código Go incorporado; o wrapper
Kotlin upstream não foi copiado. Falta rever também as dependências transitivas.

WireGuard mantém o seu próprio runtime Go. Compilar ambos na mesma APK não prova
que os runtimes funcionam no mesmo processo. O ensaio native-runtime testa as
duas ordens de carregamento JNI em API 26 e 35. Mesmo esse teste não cobre
concorrência de túneis, callbacks, suspensão ou passagem real de tráfego.

### Decisão após o teste de runtime

A execução [39074565825](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39074565825)
detetou SIGSEGV em API 35 ao carregar WireGuard depois de gomobile no mesmo
processo. API 26 passou nas duas ordens. Portanto, a incorporação futura não
deve depender da coexistência desses dois runtimes no mesmo processo.

O ensaio revisto coloca Tailscale/NetBird num serviço privado `:nova_overlay`,
com `exported=false`, e mantém WireGuard noutro processo da mesma aplicação.
O IPC de diagnóstico devolve o PID; o teste exige processos distintos e repete
a chamada JNI WireGuard depois da inicialização do overlay. O serviço atual é
exclusivo do build debug de prova: ainda não é um VpnService nem controla peers.
Os processos usam o mesmo UID Android. Esta separação resolve uma fronteira
de runtime/memória; não substitui autorização, firewall ou isolamento de rede.
As duas ordens passaram em ambos os emuladores x86_64 na
[execução corrigida](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39074985057).
Falta provar o ciclo de vida funcional e a mesma arquitetura em hardware ARM/TV.

**M0 permanece aberto:** exige pedido HTTPS por cada motor incorporado, com inscrição,
consentimento e duas pontas reais. Configuração de rascunhos e estados testados não
equivale a essa prova. Não existe nesta entrega VPN Tailscale/NetBird funcional.

Fontes técnicas consultadas:

- [WireGuard embedding](https://www.wireguard.com/embedding/).
- [Tailscale Makefile fixado](https://github.com/tailscale/tailscale-android/blob/264102cc702fbd844e900227ee02e5cbb4d7f801/Makefile).
- [NetBird script móvel fixado](https://github.com/netbirdio/android-client/blob/ad7865a2c3cc1bc940bf63512ccab1819ebf53a6/build-android-lib.sh).
- [VPN Android: consentimento e ciclo de vida](https://developer.android.com/develop/connectivity/vpn).

## Próximo ensaio

1. Validar carregamento JNI em Android após a compilação conjunta já aprovada.
2. Implementar associação de teste autenticada, com credenciais descartáveis por dispositivo.
3. Validar pedido HTTPS, troca de fornecedor e desligamento/revogação em cada motor.
4. Medir isolamento de portas, restauração após suspensão e atualização em Android TV.
5. Só então fechar M0 e avançar as integrações para a jornada Cinema/Directory.
