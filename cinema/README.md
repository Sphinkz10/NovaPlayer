# NOVA Cinema · Signature Android TV (primeira vista)

Implementação **nativa Kotlin + Jetpack Compose** da Home `SIG-01 · Home híbrida` do **Template 02 — NOVA Signature**.

## Fonte visual única
- Figma: https://www.figma.com/design/AAwpusB10YU5tXg4y8Z6P3?node-id=69-3
- 1080p: frame `69:3` (1920×1080)
- 720p: frame `80:3` (1280×720); primeira versão usa escalonamento proporcional do layout 1080p.
- Fundo hero original: art layer `69:4`.
- Artwork cartões: `69:92`, `69:101`, `88:24`, e efeito `69:110`. **São exportações das CAMADAS de arte, não da interface achatada.**

## Executar
1. Instalar Android Studio com Android SDK 35 e JDK 17.
2. Abrir a pasta `cinema/` como projeto Android/Gradle.
3. Sincronizar Gradle e executar `app` num dispositivo Android TV/emulador.
4. Inspecionar em landscape 1920x1080 ou 1280x720.
5. Usar o comando D-pad: as ações reagem ao foco e exibem estados de protótipo.

## O que esta entrega faz e não faz
- **Faz:** apresenta a estrutura da Home Signature e utiliza artwork original do Figma, com proporções, cores, textos e posições base. Tem foco D-pad visual nas ações e cartões.
- **Não faz:** login, Jellyfin, player real, VPN, categorias reais, telemetria ou autorização remota. Estas ações apresentam uma mensagem explicativa em vez de simularem sucesso.
- Não substitui `connect/` nem `server/`.
- Layout ainda precisa de captura e teste de comparação visual real na Xiaomi e de implementar os restantes ecrãs Signature.
- Usa Android Sans como fallback tipográfico nesta primeira base; a implementação da fonte Inter do design original fica pendente de integração licenciada. A revisão do espaçamento de fontes deverá considerar essa diferença.
- **Sem APK compilada nesta entrega:** o ambiente usado para preparar o código não possui Android SDK.
