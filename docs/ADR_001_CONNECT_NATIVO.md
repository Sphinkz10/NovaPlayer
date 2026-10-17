# ADR 001 — Base comum para três fornecedores nativos

Estado: contrato inicial implementado; motores Tailscale/NetBird e provas de rede pendentes.
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
| Tailscale | `tailscale/tailscale-android@264102cc702fbd844e900227ee02e5cbb4d7f801` | Makefile produz AAR móvel; não integrado nem compilado no NOVA |
| NetBird | `netbirdio/android-client@ad7865a2c3cc1bc940bf63512ccab1819ebf53a6` | Script gomobile produz `netbird.aar`, API mínima 26 e NDK 23.1.7779620; não integrado nem compilado no NOVA |

As receitas móveis consultadas requerem toolchain Go/NDK, ausente neste ambiente.
Não se deve tratar `tsnet` como um SDK Android pronto. Antes de combinar AARs gerados
por gomobile, verificar nomes de bibliotecas JNI e coexistência de runtimes Go na mesma
APK: não resolver possíveis colisões com `pickFirst`, que pode descartar um motor.
Falta fixar todos os componentes Go, rever as respetivas licenças/avisos, selecionar
a ponte Android e comprovar os três motores dentro de uma única aplicação.

**M0 permanece aberto:** exige pedido HTTPS por cada motor incorporado, com inscrição,
consentimento e duas pontas reais. Configuração de rascunhos e estados testados não
equivale a essa prova. Não existe nesta entrega VPN Tailscale/NetBird funcional.

Fontes técnicas consultadas:

- [WireGuard embedding](https://www.wireguard.com/embedding/).
- [Tailscale Makefile fixado](https://github.com/tailscale/tailscale-android/blob/264102cc702fbd844e900227ee02e5cbb4d7f801/Makefile).
- [NetBird script móvel fixado](https://github.com/netbirdio/android-client/blob/ad7865a2c3cc1bc940bf63512ccab1819ebf53a6/build-android-lib.sh).
- [VPN Android: consentimento e ciclo de vida](https://developer.android.com/develop/connectivity/vpn).

## Próximo ensaio

1. Preparar toolchain Linux Go/NDK reproduzível e integrar motores sem colisões JNI.
2. Implementar associação de teste autenticada, com credenciais descartáveis por dispositivo.
3. Validar pedido HTTPS, troca de fornecedor e desligamento/revogação em cada motor.
4. Medir isolamento de portas, restauração após suspensão e atualização em Android TV.
5. Só então fechar M0 e avançar as integrações para a jornada Cinema/Directory.
