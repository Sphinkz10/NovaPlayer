# NOVA Connect — Prova Técnica v0.3

**12 outubro 2026 · Estado: código-fonte experimental + lógica testada localmente. NÃO é APK nem uma VPN funcional aprovada.**

## Objetivo

Uma única app Android TV incorpora o motor WireGuard (biblioteca oficial `com.wireguard.android:tunnel:1.0.20260102`). Familiares não precisam de instalar outro cliente VPN. O Android continua a exigir o consentimento do sistema na primeira utilização quando aplicável. A configuração e aprovação de dispositivos pertencem ao administrador; **a associação por convite ainda NÃO foi implementada**.

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

Resultado local verificado em 12/10/2026:

| Testes | Resultado |
|---|---|
| Políticas Kotlin: conexão, privacidade, saúde, reprodução, rotas, identidade | **112/112 PASS** |
| Transportes HTTP falsos, TLS e identity mismatch | **19/19 PASS** |
| Total Kotlin/HTTP | **131/131 PASS** |
| Inspeção estática heurística de fonte | **11/11 PASS** |
| Gradle / SDK / APK / emulador | **NÃO executados** |
| WireGuard handshake e Jellyfin reais | **NÃO executados** |

Os testes HTTP são locais, com servidores de resposta fictícios. Não confirmam autenticação Jellyfin nem reprodução.

## Build Android — ainda PENDENTE

Requer Android Studio, SDK 35, Java 17 e resolução de dependências Gradle AGP `8.9.2`, Kotlin `2.0.21` e `com.wireguard.android:tunnel:1.0.20260102`.

O código não inclui `gradlew` porque não foi possível validar nem gerar o wrapper oficial neste ambiente. Abrir a pasta no Android Studio com Gradle instalado, realizar um sync e compilar um APK **debug** numa máquina Android SDK. O `applicationId` da prova é `com.novacinema.connect.poc`. A versão foi incrementada para `0.3` (versionCode 3).

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
