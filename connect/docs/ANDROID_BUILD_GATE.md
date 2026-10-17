# Gate Android / Xiaomi — lista de verificação

## Pré-requisitos

- Computador com Android Studio, Android SDK 35, JDK 17, Gradle disponível.
- Xiaomi TV Box S (2.ª geração), com Android TV/Google TV.
- Rede isolada de laboratório, IP privado HTTPS com certificado confiável, WireGuard peer temporário gerado fora do chat.
- Conta Jellyfin de teste não administradora e ID esperado do Jellyfin obtido através de canal administrativo verificado.

## C02: Compilar e inspecionar

- [ ] Sincronizar o Gradle; resolver `GoBackend`, `Config` e `Tunnel` oficiais; compilar APK de debug.
- [ ] Inspecionar manifest fundido (VPN service declarado por AAR, permission, app labels, backup/cleartext).
- [ ] Validar instalação, foco por comando e textos de diagnóstico numa Xiaomi física.
- [ ] Confirmar que o APK instalado é `com.novacinema.connect.poc` e não colide com apps existentes.

## C03/C04: VPN real

- [ ] Dispositivo sem perfil: não inicia ligação; não solicita dados de admin.
- [ ] Consentimento Android inicial; negação sem tentativa de bypass.
- [ ] Perfil temporário associado por mecanismo administrativo controlado.
- [ ] Handshake com túnel restrito apenas à app, apenas para endereço /32 autorizado.
- [ ] Túnel não encaminha outras apps nem dá acesso geral ao NAS.
- [ ] Negação de acesso a TrueNAS UI, SSH, SMB e IPs externos à ACL.
- [ ] Teste de VPN já ativa e quando o consentimento é revogado.
- [ ] Teste de reabertura da app, suspensão/reinício e mudança de Wi-Fi/ethernet.

## C05: Jellyfin / certificado

- [ ] HTTPS válido do endpoint privado, identidade esperada do servidor corresponde.
- [ ] Simular certificado inválido; estado TLS_VALIDATION_FAILED, sem fallback HTTP.
- [ ] Simular servidor Jellyfin trocado; mismatch sem login nem reprodução.
- [ ] Simular 503, 429, falha de rede e 200 inválido; não apagar dados offline.
- [ ] Autenticação por familiar, permissões de biblioteca e token individual.

## C06/C07/C08: Produto e segurança

- [ ] Convite individual de utilização única aprovado pelo administrador.
- [ ] Renovação e revogação de peer, chave, sessão e dispositivo.
- [ ] Player Media3 integrado, Direct Play, pistas e oito testes G2.
- [ ] Carga simultânea remota e upload real medidos, não estimados.

**Não há gates Android concluídos nesta versão.**
