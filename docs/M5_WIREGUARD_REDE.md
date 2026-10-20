# M5 — Primeira prova de rede WireGuard nativa

Registo da primeira prova, revisão `3434c8b`. O incremento seguinte substitui a chave de TV preparada pelo anfitrião por [geração no Android e inscrição aprovada no Control](M5_INSCRICAO_WIREGUARD.md). Os resultados abaixo pertencem à primeira execução e permanecem como histórico verificável.

**Primeira prova WireGuard → HTTPS NOVA aprovada em laboratório em 20-10-2026: API 26 e 35, 16/16 verificações em cada.** A instalação de teste disponível continua a ser [NOVA Cinema 0.9 LAN](M4_DISTRIBUICAO_ANDROID.md). Esta prova não ativa o fornecedor no Control nem entrega perfis VPN às TVs de produção.

## Percurso executado

Uma APK experimental usa o GoBackend oficial já incorporado na NOVA. O Android apresenta o seu diálogo de autorização VPN; o ensaio interage com esse diálogo e verifica `VpnService.prepare`. O perfil contém apenas a aplicação NOVA e uma rota IPv4 `/32` para um serviço dedicado.

A outra ponta é WireGuard do kernel Linux num namespace descartável. O namespace recebe apenas UDP WireGuard pela interface de transporte e TCP 9444 pela interface do túnel. A API NOVA de cliente executa ali com TLS 1.3, certificado/SAN explícitos e uma credencial de dispositivo aprovada. O tráfego não termina no Jellyfin ou na interface administrativa.

O emulador alcança um transporte UDP local que encaminha os datagramas WireGuard cifrados para o namespace. Não há encaminhamento TCP nem `adb reverse` para o serviço privado. O anfitrião não recebe uma rota específica para o IP de serviço do túnel. O contador e o timestamp de handshake são consultados no gateway real; o simples estado UP do Android não basta.

## Verificações

- Serviço privado inacessível antes da VPN; consentimento Android real.
- Perfil WireGuard protegido pelo Android Keystore, persistência após reinício do processo, adulteração recusada e eliminação local da chave.
- Perfis de túnel completo e de outra aplicação recusados antes de estabelecer o túnel.
- Chamada autenticada à API NOVA através do GoBackend e WireGuard Linux, confirmando as identidades de servidor e dispositivo.
- Certificado HTTPS diferente recusado dentro do túnel.
- Rotas administrativas ausentes da API de cliente; firewall recusa TCP 22/9443 e entrada TCP pela rede de transporte. Serviços-canário realmente a escutar nessas portas confirmam que a recusa não resulta de portas vazias.
- Revogação do dispositivo na NOVA devolve 401, mesmo com o túnel UP; não se anuncia estado CONNECTED sem autorização.
- Remoção do peer no gateway bloqueia novo tráfego privado. Desligar o motor não introduz uma rota pública alternativa.

Os dispositivos/chaves/certificados são descartáveis e isolados por job. A identidade de dispositivo é preparada pelo harness através das classes reais de aprovação NOVA; não representa um percurso de inscrição no Control. Os ficheiros privados ficam em diretórios temporários e no sandbox debug do emulador, sem publicação nos artefactos.

## Repetição e evidências

Workflow `wireguard-network.yml`, com emuladores API 26/35 e fonte WireGuard Android fixada no Gradle. O workflow requer uma VM Linux descartável com privilégios para criar namespaces e interfaces WireGuard. O script recusa uma execução normal ou um dispositivo físico. Não usar no NAS.

Compilação da variante experimental:

```text
bash gradlew :app:assembleDebug :app:assembleDebugAndroidTest -PnovaWireGuardProof=true
```

O flag acrescenta apenas Activity de consentimento debug e instrumentação. A APK assinada 0.9, o seu identificador, a chave persistente e a imagem do servidor mantêm-se preservados. O build normal não inclui essa Activity ou o perfil de ensaio.

Os relatórios `wireguard-network.json` identificam API, revisão, APK, verificações, handshake e contadores. As mensagens de erro guardam tipos/linhas sem chaves, tokens ou payloads. A [execução WireGuard 39459022187](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39459022187) passou à primeira tentativa nos dois emuladores. Revisão executável `3434c8b7b64a22303e9438c428d5302b06a0fa14`; árvore do merge CI `394a5b2d77d1d74a1156ea15a577688b957bae69` conferida igual à dessa revisão.

| Prova no gateway | API 26 | API 35 |
|---|---|---|
| Handshake observado | Sim | Sim |
| Bytes recebidos/enviados pelo peer | 8452 / 8556 | 9012 / 8972 |
| Pacotes recusados pelo firewall | 6 | 6 |
| Verificações completas | 16/16 | 16/16 |

Estes contadores demonstram tráfego e recusas neste ensaio; não medem bitrate sustentado ou desempenho de vídeo. Os artefactos foram conferidos pelos digests GitHub e o hash de cada APK experimental corresponde ao relatório. A reconstrução normal da distribuição produziu o mesmo ficheiro sem assinatura `a91fc95537cb8b4df53c50db2b5ea3e735e56fe36b985bdab2203497717d3d1f` da entrega 0.9. Não há nova APK de distribuição a instalar neste incremento.

Regressões desta revisão: [CI principal 8/8](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39459021983), [associação/player/LAN API 26/35](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39459022095) e [distribuição/update API 26/35](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39459021889) aprovados. Linux Python 3.12/3.13: 304/304 cada; Windows: 298 aprovados + 6 exclusões POSIX cada; Kotlin: 203. Build e lint local da variante WireGuard aprovados, com 0 erros e 56 avisos.

A entrega local `NOVA_M5_WIREGUARD_2026-10-20` contém fontes, relatórios e hashes. Não inclui uma APK experimental para instalar nem chaves privadas. `M5_WIREGUARD_RESULTADOS.json` preserva a proveniência CI e o vínculo à entrega 0.9.

## Trabalho ainda necessário para M5

| Etapa | Estado |
|---|---|
| WireGuard incorporado → HTTPS NOVA com autorização e firewall | Aprovado em API 26/35, gateway Linux real |
| Chave de TV criada no dispositivo e inscrição autenticada por associação | Implementada no [incremento seguinte](M5_INSCRICAO_WIREGUARD.md) |
| Aprovação/revogação de pedidos no Control | Implementada no incremento seguinte; sem declarar peer instalado |
| Configuração idempotente e adaptador restrito do gateway | Por implementar |
| Instalação compatível do gateway no TrueNAS, TLS e endereços remotos | Por implementar |
| Bootstrap Directory fora da LAN, catálogo/player e renovação remota | Por implementar |
| Revogação automática no fornecedor, troca de rede, suspensão e reconexão | Por implementar |
| Jornadas nativas Tailscale e NetBird, cada uma com HTTPS/isolamento próprios | Por implementar |

O endpoint UDP precisa de ser alcançável; o ensaio local não resolve NAT real, encaminhamento de portas ou um gateway externo. Não configura o router/NAS. IPv6, outros formatos de media, hardware ARM/TV e segurança final não são certificados por este teste.

M0/M5 continuam abertos até às provas dos três motores e aos percursos de produto exigidos no [roadmap](ROADMAP_INSTALACAO_SERVER_TV_v0_2.md). SEC-01…12: 0/12 aceitações finais.

Fontes: [WireGuard Quick Start](https://www.wireguard.com/quickstart/), [WireGuard Android GoBackend](https://github.com/WireGuard/wireguard-android/blob/master/tunnel/src/main/java/com/wireguard/android/backend/GoBackend.java), [Android VPN](https://developer.android.com/develop/connectivity/vpn).
