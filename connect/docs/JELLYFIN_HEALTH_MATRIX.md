# Matriz Jellyfin — v0.3

O endpoint `GET /System/Info/Public` comprova apenas a **resposta pública de saúde** do serviço. Não substitui a autenticação de utilizador nem garante que um filme seja reproduzível.

| Resultado | Estado NOVA | Repetir automaticamente? | Ação do utilizador/admin |
|---|---|---|---|
| 200 / produto Jellyfin / ID esperado / wizard completo | READY | Não | Continuar para autenticação do familiar |
| 200 / wizard incompleto | SETUP_REQUIRED | Não | O administrador termina configuração |
| 200 / ID diferente | SERVER_IDENTITY_MISMATCH | **Não** | Bloquear e verificar a configuração |
| 200 / JSON incorreto, sem ID ou produto diferente | UNEXPECTED_RESPONSE | Não | Rever endpoint/configuração |
| 401 | AUTH_REQUIRED | Não | Iniciar autenticação autorizada |
| 403 | FORBIDDEN | Não | Rever permissões, sem elevar privilégios |
| 404 | WRONG_ENDPOINT | Não | Rever o endpoint |
| 408, 425, 500, 502, 503, 504 | TEMPORARILY_UNAVAILABLE | Sim, limitado | Manter biblioteca em cache |
| 429 | RATE_LIMITED | Sim, respeitar Retry-After | Esperar, evitar avalanche de requests |
| Redirecionamento 30x | REDIRECT_REJECTED | Não | Impedir saída para outro host |
| TLS handshake/certificado/hostname rejeitado | TLS_VALIDATION_FAILED | **Não** | Corrigir certificados; sem ignorar TLS |
| Permissão de segurança / SecurityException | SECURITY_BLOCKED | **Não** | Rever política do dispositivo |
| Socket timeout / rede inacessível | OFFLINE | Sim, limitado | Mostrar estado offline sem apagar dados |

Em todos os erros, títulos, watchlist, pedidos e calendário não são apagados. O resultado 200 é apenas compatibilidade básica; a verdadeira API deverá verificar o utilizador e o arquivo visível.
