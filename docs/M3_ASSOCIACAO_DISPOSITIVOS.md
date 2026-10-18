# M3 — associação de dispositivos, primeiro incremento

Estado: NOVA Server `0.3.0-dev`. Implementação de laboratório; M3 ainda não concluída. A entrega M2 `0.2.0-lab` e a sua imagem por digest continuam identificadas no guia M2. Não substituir a instalação M2 por esta revisão sem backup offline e plano de restauro: o schema passa de 1 para 2.

Cliente Android de laboratório implementado no incremento seguinte: [M3_CLIENTE_ANDROID.md](M3_CLIENTE_ANDROID.md). A confirmação inicial usa ficheiro público e impressão digital por canal de confiança; Directory e renovação integrada de certificados continuam pendentes.

## O que já funciona

- Identidade UUID persistente do NOVA Server, distinta da identidade Jellyfin. Não é ainda uma chave de assinatura nem registo no Directory.
- Cliente pede associação e apresenta código de oito caracteres. O proprietário introduz o código no Control, consulta nome/código e aprova ou recusa explicitamente.
- Código visível e segredo de polling independentes; apenas hashes na base. Pedido expira em dez minutos, só pode ser consumido uma vez e tem polling limitado (cinco segundos inicialmente; pedidos antecipados aumentam o intervalo).
- Credenciais opacas de dispositivo com âmbito exclusivo `device:read`: identificam a associação e permitem obter um descriptor pelo canal HTTPS validado. Não autorizam administração, Jellyfin, biblioteca, streaming ou configuração VPN.
- Access token de cinco minutos e refresh rotativo, com prazo absoluto de trinta dias. Cada renovação invalida o access token anterior. Reutilizar um refresh consumido revoga também o sucessor. O cliente deve serializar renovações; se perder a resposta, terá de associar novamente, sem repetir silenciosamente o refresh antigo.
- Lista e revogação no Control. A próxima autorização é recusada após revogação; isto ainda não prova interrupção de vídeo/túnel, que não existem neste incremento.
- Transições SQLite atómicas entre processos, limites globais e por origem, teto de pedidos/dispositivos e mensagens sem credenciais. Pedidos de início: dez por origem e 64 globais em dez minutos; consulta/decisão de proprietário: vinte por dez minutos; chamadas do cliente: sessenta por origem e 240 globais por minuto. Sem confiança em cabeçalhos de proxy. Máximo de 50 registos de dispositivo ainda dentro do prazo; credenciais requerem nova associação após 10 000 rotações.
- Backup/restauro suporta os schemas 0/1/2. Restauro apaga códigos pendentes e credenciais de dispositivos e marca associações como revogadas, preservando a identidade do servidor. A restrição a um único utilizador Jellyfin mantém-se.

## Separação de APIs

O processo administrativo existente continua em loopback. A API cliente é outro processo e não monta o Control, rotas administrativas ou proxy Jellyfin. O Compose/gerador TrueNAS M2 **não inicia nem publica** a API experimental de dispositivos.

| API cliente HTTPS | Operação |
|---|---|
| `POST /api/v1/device/authorize` | JSON `label`; devolve `device_code`, `user_code`, `server_id`, prazo e intervalo |
| `POST /api/v1/device/token` | JSON `device_code`; aguarda aprovação ou entrega credenciais uma única vez |
| `POST /api/v1/device/refresh` | JSON `refresh_token`; troca atómica e deteção de reutilização |
| `GET /api/v1/device/me` | Bearer do dispositivo; devolve identidade, âmbito e descriptor |
| `POST /api/v1/device/logout` | Bearer do dispositivo; revoga apenas a sua própria associação |

No Control: `POST /api/v1/admin/devices/inspect`, `POST /api/v1/admin/devices/decision`, `GET /api/v1/admin/devices` e `DELETE /api/v1/admin/devices/{id}` exigem sessão do proprietário. A decisão inclui código e identificador do pedido consultado. O nome do dispositivo é texto não confiável; o proprietário deve comparar também o código apresentado pelo seu dispositivo.

O protocolo JSON próprio segue os princípios de [RFC 8628](https://www.rfc-editor.org/rfc/rfc8628) e da [rotação de refresh tokens em RFC 9700](https://www.rfc-editor.org/rfc/rfc9700); não é anunciado como servidor OAuth/OIDC compatível. A obtenção de confiança inicial e a descoberta via Directory ainda não estão implementadas. Não usar códigos enviados por terceiros para autorizar dispositivos.

## Ensaiar no PC

A partir de `server/`, com as dependências de desenvolvimento instaladas:

```text
python -m pytest -q
python scripts/smoke_devices_tls.py --output test-results/devices
python scripts/smoke_browser.py --output test-results/browser
```

O ensaio TLS gera certificados temporários com OpenSSL, lança dois processos em loopback e realiza associação/aprovação, token, renovação, reinício e revogação. Verifica recusa de CA desconhecida, hostname errado e HTTP. Não usa `verify=False`, não altera a trust store do PC e apaga os certificados/estado de teste no fim. O navegador verifica aprovação/revogação, nome malicioso como texto e descarte de uma resposta de consulta que deixou de corresponder ao código introduzido. Em Windows com Edge pode usar-se `--channel msedge` no ensaio do navegador.

Para iniciar manualmente o serviço experimental, fornecer `NOVA_STATE_DIR` igual ao processo administrativo, `NOVA_CLIENT_ORIGIN=https://127.0.0.1:8920`, `NOVA_CLIENT_CERT` e `NOVA_CLIENT_KEY` com certificado/chave válidos, e executar `python -m nova_server.client_api`. O processo só escuta em `127.0.0.1`; a CA e o nome têm de ser validados pelo cliente. Não substituir por arranque HTTP com cabeçalhos de proxy. Não disponibiliza a TV na LAN nem instala certificados na TV.

## Estado de validação e limites

Resultados locais Windows: suíte Python e ensaios reais HTTPS/Edge aprovados; consultar a execução CI associada ao commit para Linux, matriz Python e Docker. A CI executa HTTPS e navegador em Python 3.12/3.13, Linux/Windows. O ensaio Docker inclui backup/restauro de uma associação e de um pedido aprovado ainda não consumido, verificando que ambos perdem autorização. Os relatórios JSON não contêm códigos ou tokens.

Ainda por implementar na M3: conta/servidor no Directory com prova de posse, descoberta autenticada, bootstrap/renovação TLS integrados com descoberta na TV, permissões por utilizador/biblioteca Jellyfin e descriptor com autorização de media. Não foram executados testes em TV física ou no TrueNAS.

Próxima sequência: validar o cliente Android de laboratório → Directory e permissões → associação com descoberta e confiança integradas → M4, catálogo e primeiro filme. WireGuard/Tailscale/NetBird continuam nativos no plano M0/M5; esta associação não cria túneis.
