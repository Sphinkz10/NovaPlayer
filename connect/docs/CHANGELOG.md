# Changelog

## v0.3 · 2026-10-12

- Impedido falso acesso LAN através de URL público arbitrário, mesmo com `lanVerified=true`: POC apenas aceita IP HTTPS privado numérico no modo LAN.
- HTTPS: falhas TLS e de permissão de segurança diferenciadas de estado offline; sem retry automático para falha de certificado.
- Identidade do servidor Jellyfin verificada com ID esperado no perfil cifrado; resposta de outro servidor é bloqueada.
- `ProvisioningStore` atualizado para formato `nova-profile-v3` com AES-GCM, AAD específica da app e armazenamento de ID esperado. Perfil antigo v0.2 **não é migrado automaticamente**.
- Rejeição de rotas WireGuard repetidas ou listas de CIDRs malformadas com vírgulas vazias.
- Retoma controlada da VPN ao reabrir a Activity com consentimento válido e perfil existente (não é always-on nem boot service).
- Adicionados testes injetáveis para erros TLS, segurança, timeout, hostname público e identidade Jellyfin.
- Atualizados `versionName 0.3`, README, matriz de risco e gates.
- 112/112 testes de políticas + 19/19 mock de HTTP = **131/131**; inspeção heurística **11/11**.

## v0.2 · 2026-10-12

- Política de rede privada, HTTP probe, estado Jellyfin e player decision engine.
- Esqueleto Android com túnel WireGuard e armazenamento Android Keystore.
- 104 testes Kotlin e mock HTTP.
