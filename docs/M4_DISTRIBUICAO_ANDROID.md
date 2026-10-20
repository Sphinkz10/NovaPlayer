# M4 — Distribuição Android com identidade persistente

Pacote de distribuição em validação. A instalação LAN e a recuperação anteriores mantêm as respetivas provas em [M4_RECUPERACAO_LAN.md](M4_RECUPERACAO_LAN.md).

## Identidade e primeira instalação

`NOVA Cinema`, pacote **`com.novacinema.cinema`**, versão **0.9-m4-lan / 9**, mínimo Android API 26, target 35. Inclui arm64-v8a, armeabi-v7a, x86 e x86_64. A variante release tem debug desativado, backups Android desativados e mantém as regras HTTPS existentes. A interface continua a identificar o ensaio LAN M4; não anuncia os três fornecedores VPN como implementados.

Este pacote é diferente de `com.novacinema.connect.poc`, usado nas APKs de laboratório. Pode coexistir com a app anterior; não se instala como atualização dela. Na primeira abertura configurar Directory/fingerprint, entrar com a conta e aprovar um novo dispositivo no Control. Os dados privados da app antiga não são copiados. Revogar a associação antiga no Control quando deixar de ser necessária.

As atualizações de distribuição devem manter o identificador, a chave e um `versionCode` crescente. A ferramenta recusa uma chave diferente do certificado público fixado em [release-identity.json](../connect/release-identity.json). Não cria nem substitui uma chave durante o build ou assinatura.

## Guarda da chave

A chave privada persistente desta entrega foi criada fora do workspace, em `%LOCALAPPDATA%/NOVA/cinema-signing-v1/`, com ACL privado Windows. Apenas o certificado e o fingerprint são públicos. Nem o Git, nem as Actions, nem o pacote de instalação incluem a chave ou a palavra-passe.

O ficheiro `nova-cinema.p12` está cifrado. `password.dpapi` permite utilizar a palavra-passe apenas no perfil Windows que a protegeu. A nota privada `LEIA-ME_PRIVADO.md` explica a recuperação. **Guardar uma cópia offline do `.p12` e, separadamente, a palavra-passe de `PASSWORD_RECUPERACAO_PRIVADO.txt`.** Essa cópia offline depende do proprietário e não foi executada automaticamente. O ficheiro de recuperação da palavra-passe é legível por quem tenha acesso à pasta privada; não copiar a pasta inteira para uma entrega ou backup partilhado.

Perder a chave e a palavra-passe impede continuar as atualizações assinadas com esta identidade. Não gerar outra chave silenciosamente. A assinatura persistente identifica o editor da APK; não certifica a segurança da plataforma nem substitui os ensaios físicos.

## Build e assinatura de uma atualização

Requer JDK 17, Python 3.12/3.13 e Android SDK/build tools 35. A compilação usa as dependências bloqueadas e verificadas do projeto. Em `connect/`:

```powershell
# Exemplo da próxima versão: escolher um código ainda não distribuído.
.\gradlew.bat :app:assembleRelease :app:lintRelease -PnovaVersionCode=10 --no-daemon --console plain

$novaProtected = Get-Content "$env:LOCALAPPDATA\NOVA\cinema-signing-v1\password.dpapi" | ConvertTo-SecureString
$env:NOVA_SIGNING_PASSWORD = [System.Net.NetworkCredential]::new('', $novaProtected).Password
try {
    python scripts/distribution.py sign --input app/build/outputs/apk/release/app-release-unsigned.apk --output ..\dist\NOVA-Cinema-seguinte.apk --keystore "$env:LOCALAPPDATA\NOVA\cinema-signing-v1\nova-cinema.p12" --previous ..\NOVA-Cinema-anterior.apk
} finally {
    Remove-Item Env:NOVA_SIGNING_PASSWORD
}
python scripts/distribution.py verify --apk ..\dist\NOVA-Cinema-seguinte.apk
```

Substituir `--previous` pela APK de distribuição efetivamente anterior. Um ficheiro de saída existente é recusado. Guardar o relatório JSON produzido junto da APK. A palavra-passe não é passada na linha de comandos nem ao daemon Gradle. A assinatura é efetuada offline pelo `apksigner` oficial.

Para uma instalação nova, usar a imagem e o guia de recuperação LAN da entrega. O código do servidor não mudou neste incremento; a imagem de recuperação verificada continua aplicável. O identificador Android muda apenas a identidade da app no dispositivo, sem alterar a identidade do servidor/Directory.

## Provas e limites

Resultados finais dos emuladores por registar. O gate de assinatura usa o SDK real com chaves descartáveis: criação exclusiva, integridade, pin do certificado, recusa de debug, chave/palavra-passe erradas, substituição de ficheiros e regressão de versão, além de assinatura da versão seguinte. O gate Android instala a variante não depurável, observa o ecrã inicial, recusa outra assinatura, atualiza para um código superior preservando UID/dados e recusa downgrade.

As chaves descartáveis da CI são distintas da chave persistente. O relatório da APK final liga o hash do build sem assinatura ao binário assinado localmente; a verificação independente confere o certificado público. Os ensaios de login/player continuam na instrumentação debug, em execução separada. Não confundir a assinatura final verificada offline com uma instalação desse binário numa TV física.

M3 continua concluída em software. M4 mantém o ensaio físico no TrueNAS, Xiaomi Box S2 e Chromecast. WireGuard, Tailscale e NetBird nativos completos continuam M5; SEC-01…12: 0/12 aceitações finais.

## Referências

- [Android — assinatura e continuidade de atualizações](https://developer.android.com/studio/publish/app-signing)
- [Android — apksigner](https://developer.android.com/tools/apksigner)
- [Android — zipalign](https://developer.android.com/tools/zipalign)
