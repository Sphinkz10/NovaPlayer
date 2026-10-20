# NOVA Cinema / Connect — Distribuição LAN 0.9

> Estado atual: [M4 Distribuição Android](../docs/M4_DISTRIBUICAO_ANDROID.md), com pacote de distribuição próprio e assinatura persistente offline. Instalação LAN, catálogo/player e recuperação integrada foram ensaiados em laboratório. A [M3](../docs/M3_FECHO.md) está concluída em software. Aparelhos físicos e jornadas VPN permanecem pendentes. Os detalhes da fase 1 abaixo são históricos onde divergirem destes documentos.

**Base inicial de 17 outubro 2026:** diagnóstico e lógica de domínio. A reprodução local foi acrescentada e ensaiada na M4 em 20 outubro.

Esta fase acrescenta deteção de SDK/ABIs/Leanback, contratos WireGuard/Tailscale/NetBird e estados que não confundem túnel UP com serviço autorizado. Não há restrição a Xiaomi/Chromecast: Android API 26+ e ABIs compatíveis definem a base. Tailscale e NetBird são explicitamente não implementados; o motor WireGuard conserva a prova existente.

Build reproduzível por dependências fixadas: JDK 17, SDK 35, `gradlew.bat :core:verifyCore :app:assembleDebug :app:lintDebug` em Windows, ou `bash gradlew ...` em Linux. Wrapper 8.11.1, checksum oficial da distribuição e do JAR, locks e checksums de dependências incluídos. Isto não promete APKs bit a bit iguais: a assinatura debug é local.

Para atualizar checksums após revisão: `bash gradlew -I scripts/resolve_build_tools.gradle :app:resolveBuildToolArtifacts :core:verifyCore :app:assembleDebug :app:lintDebug --write-locks --write-verification-metadata sha256`. Rever o diff; a CI normal não regenera nem aceita novos checksums automaticamente.

A política de domínio distingue remux, conversão de áudio, vídeo autorizado e codecs/legendas incompatíveis. O primeiro player M4 usa apenas o ficheiro original: as rotas de remux/transcodificação continuam pendentes. [Resultados históricos da fase 1](../docs/FASE_1_RESULTADOS.md).

## Objetivo

Uma única app Android TV deve incorporar os motores dos três fornecedores. A APK normal contém a base WireGuard (`com.wireguard.android:tunnel:1.0.20260102`); as jornadas remotas completas pertencem à M5. O Android exige consentimento do sistema quando aplicável. A associação por código e aprovação do proprietário já está implementada na M3; não fornece ainda perfis VPN.

Este projeto **não faz alterações à UniFi Dream Router, TrueNAS, Jellyfin ou repositórios existentes**. Não guarda nem fornece chaves de produção.

## O que existe nesta prova

- Código Android de uma `Activity` de diagnóstico para Android TV, `GoBackend` WireGuard e `VpnService.prepare`.
- Regras Kotlin reutilizáveis para selecionar LAN privada validada, VPN preparada ou indisponibilidade, sem fallback público silencioso.
- Configuração WireGuard limitada à **aplicação NOVA** (`IncludedApplications` contém apenas o packageId) e a **rotas IPv4 privadas /32** para o gateway autorizado.
- Perfil cifrado através de Android Keystore, AES-GCM e AAD específica da app. A v0.3 inclui **ID de servidor Jellyfin esperado**, fornecido pelo futuro administrador; um servidor com outro ID é recusado.
- Verificação anónima e limitada de `GET /System/Info/Public`, sem seguir redirecionamentos, sem aceitar HTTP não cifrado em produção, com timeouts de 4s/5s e corpo até 16 KiB.
- Estados READY, SETUP_REQUIRED, AUTH_REQUIRED, FORBIDDEN, WRONG_ENDPOINT, RATE_LIMITED, TEMPORARILY_UNAVAILABLE, REDIRECT_REJECTED, **TLS_VALIDATION_FAILED, SECURITY_BLOCKED, SERVER_IDENTITY_MISMATCH**, UNEXPECTED_RESPONSE e OFFLINE.
- Retoma de ligação **ao voltar a abrir a Activity**, apenas se existir perfil e a autorização VPN ainda for válida. **Não implementa um serviço de reconexão persistente depois do arranque do Android.**
- Política de reprodução independente que só admite transcodificação de vídeo com aprovação **do utilizador e do administrador**, sem exceções silenciosas.
- Proteção contra LAN pública indevidamente marcada como verificada, URLs com traversal codificado, rotas repetidas e endpoints públicos.

## Executar testes reais disponíveis neste ambiente

JDK 17+, `kotlinc` instalado:

```sh
./scripts/run_core_tests.sh
python3 scripts/check_source_hygiene.py
```

Resultado local verificado em 17/10/2026 (fase 1):

| Testes | Resultado |
|---|---|
| Políticas Kotlin: conexão, privacidade, saúde, reprodução, rotas, identidade | **116/116 PASS** |
| Transportes HTTP falsos, TLS e identity mismatch | **19/19 PASS** |
| Contratos de fornecedor e compatibilidade | **30/30 PASS** |
| Total Kotlin/HTTP/fornecedores | **165/165 PASS** |
| Inspeção estática heurística de fonte | **11/11 PASS** |
| Gradle Wrapper / build APK / assinatura debug | **Aprovados em Windows, JDK 17 / SDK 35** |
| Android lint | **0 erros; 10 avisos**, descritos no relatório de fase |
| TV / emulador | **Não executados nesta fase** |
| WireGuard handshake e Jellyfin reais | **NÃO executados** |

Os testes HTTP são locais, com servidores de resposta fictícios. Não confirmam autenticação Jellyfin nem reprodução.

## Build Android — verificado localmente

Requer Android Studio, SDK 35, Java 17 e resolução de dependências Gradle AGP `8.9.2`, Kotlin `2.0.21` e `com.wireguard.android:tunnel:1.0.20260102`.

O código inclui `gradlew` e `gradlew.bat`. O `applicationId` da prova é `com.novacinema.connect.poc`, versão `0.4-phase1` (versionCode 4). A APK gerada fica em `app/build/outputs/apk/debug/app-debug.apk`. Os resultados `LOCAL_TEST_RESULTS.txt`, `LOCAL_STATIC_RESULTS.txt` e o gate em `docs/ANDROID_BUILD_GATE.md` preservam evidência histórica v0.3; o estado atual está no relatório da fase 1.

**Não instalar em familiares nem ligar a chaves de produção** antes dos testes obrigatórios. A classe `ProvisioningStore.provisionAdminOnly` é uma API interna de demonstração, **não** um endpoint de associação seguro.

## Limiar de segurança para a fase seguinte

1. **Admin onboarding:** convite assinado, válido uma vez, aprovação por dispositivo, TTL, revogação e rotação da chave.
2. **HTTPS privado:** certificado confiável para o hostname/IP real, sem desativar validação de certificados. O PoC exige IP numérico privado; um IP HTTPS precisa de certificado com SAN IP válido. Um domínio interno verificado com mapeamento privado está pendente de arquitetura.
3. **Segurança por rede:** testar que o convidado NÃO chega a TrueNAS UI, SMB, SSH, impressoras nem outros dispositivos. Túnel por-app e rota /32 não são firewall no NAS.
4. **Android:** compilar, inspecionar manifest final e consentimento VPN, testar conflitos com outras VPNs e ciclo de vida com Wi-Fi/ethernet.
5. **Jellyfin:** autenticar um utilizador limitado e testar identificador de servidor, estado de biblioteca e quotas.
6. **Media:** Media3, Direct Play na Xiaomi, áudio/legendas, 8 testes G2 e desempenho remoto com a ligação de 500 Mbps upload (ainda por medir).

## Organização

```text
app/            Android TV diagnostic harness + WireGuard adapter
core/           Políticas Kotlin JVM testáveis sem Android
core/src/test/  Casos de política e mock HTTP
scripts/        Testes JVM + inspeção heurística de segurança
docs/           Matriz Jellyfin, segurança, gates de build, changelog
```

**Não é a interface Premium NOVA Cinema final nem uma prova de túnel funcional.** Acesso remoto e configuração da UniFi ficam inalterados.

## Associação Android M3 · 0.5-pairing-lab

A APK normal inclui agora a interface de associação por código ao NOVA Server, confirmação da identidade importada, HTTPS com certificado fixado e sessão cifrada com Android Keystore. Seguir [o guia de laboratório](../docs/M3_CLIENTE_ANDROID.md). Não disponibiliza ainda filmes, Directory ou ligação VPN automática. O workflow Android device pairing TLS verifica API 26/35 contra o servidor real.
