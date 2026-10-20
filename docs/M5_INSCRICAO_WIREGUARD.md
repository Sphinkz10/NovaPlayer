# M5 — Inscrição WireGuard por TV e aprovação no Control

Incremento de desenvolvimento posterior à [primeira prova de rede](M5_WIREGUARD_REDE.md). A TV passa a gerar a sua chave WireGuard; Core recebe apenas a chave pública, ligada à associação NOVA existente. O proprietário compara a impressão digital e aprova ou revoga o pedido no Control.

A APK instalável mantém-se [NOVA Cinema 0.9 LAN](M4_DISTRIBUICAO_ANDROID.md), reutilizada com a assinatura original. O servidor recebe uma imagem nova com as correções de arranque e dependências descritas abaixo. O novo botão **Pedir WireGuard · laboratório** só aparece em builds depuráveis. Não há uma nova APK de distribuição neste incremento. A M3 de software continua concluída; M5 continua em desenvolvimento.

## Percurso implementado

1. Associar a TV ao NOVA Server e verificar a sessão pela API HTTPS com certificado fixado.
2. Gerar uma chave individual com a biblioteca WireGuard incorporada. Guardar os bytes privados cifrados com AES-GCM, usando uma chave de proteção do Android Keystore. Isto não afirma que o X25519 é executado em hardware.
3. Persistir a chave antes de enviar `POST /api/v1/device/wireguard`, contendo exclusivamente `public_key`. Um timeout pode ser repetido com a mesma chave sem criar outro pedido.
4. Mostrar SHA-256 dos 32 bytes públicos na TV e no Control. O proprietário revê TV, conta e impressão digital; a decisão exige a revisão atual do pedido.
5. Guardar a aprovação. O Control mostra **Aprovado · gateway por confirmar**. Nenhuma operação HTTP executa comandos, instala peers ou muda rotas.

`GET /api/v1/device/wireguard` devolve apenas o pedido do próprio dispositivo. O proprietário consulta todos através de `GET /api/v1/admin/connect/wireguard/enrollments` e decide através de `POST .../{device_id}` com `revision` e `approve`. As superfícies de cliente e administração permanecem separadas, sem enumeração de outras TVs pelo cliente.

| Estado da inscrição | Significado |
|---|---|
| `pending` | Chave pública recebida de um dispositivo associado; aguarda proprietário |
| `approved` | Proprietário aprovou esta chave; instalação no gateway por implementar |
| `revoked` | Pedido revogado, associação revogada/expirada ou conta desativada; não pode ser reaprovado |

Em todos os estados: `gateway_state=not_verified` e `remote_access_enabled=false`. Não existe uma API que aceite um estado `applied`. Aprovar uma chave não fecha o ensaio do gateway nem concede acesso a media.

## Persistência e revogação

- Uma chave imutável por associação; a mesma chave não pode inscrever duas TVs. Chaves malformadas, não canónicas ou pontos X25519 de baixa ordem são recusados. Campos de chave privada, comandos, rotas ou aprovação enviados pela TV são recusados sem eco dos valores.
- Chave local ligada à identidade do servidor, origem HTTPS, dispositivo e conta. Corrupção ou perda da chave Keystore falha sem gerar uma identidade substituta. Para recuperar, revogar a associação anterior e associar novamente.
- Revogação do dispositivo, logout, reutilização de refresh e revogação da conta invalidam a inscrição na mesma transação. A expiração também impede consultar, criar ou aprovar o pedido. A limpeza de dispositivos expirados remove os pedidos dependentes.
- O restauro NOVA revoga inscrições presentes no snapshot. A tabela é uma extensão aditiva do schema 3; snapshots anteriores sem essa tabela continuam suportados. Não contém chaves privadas ou tokens WireGuard.
- Esquecer a associação na TV elimina a inscrição local e a chave de proteção. Se o servidor estiver offline, a revogação remota continua a exigir o Control. A remoção efetiva de peers num gateway de produto ainda não está automatizada.

## Prova integrada

O workflow WireGuard usa dois serviços distintos: inscrição HTTPS de laboratório na rede local do emulador, e HTTPS privado dentro do namespace WireGuard. O primeiro partilha o estado Core, mas não encaminha TCP para o IP do túnel. Não se instala peer até a TV enviar a chave pública e a API administrativa aprovar o pedido.

O harness descartável lê a chave aprovada, instala-a no WireGuard Linux e confere `allowed-ips`. Os parâmetros públicos do gateway vêm de uma fixture de laboratório; o perfil privado é construído dentro do Android, sem exportar a chave privada. Depois repetem-se consentimento Android, handshake, HTTPS autenticado, recusas do firewall e revogações. Isto prova a combinação inscrição/aprovação/motor no laboratório; o harness não é um instalador TrueNAS.

Também se verifica persistência após reinício do processo, rejeição de outra associação, adulteração do ciphertext, perda da chave Keystore e limpeza ao esquecer a associação. Os relatórios publicados não contêm a fixture privada ou material de chave.

Resultados e proveniência CI: pendentes de registo após a execução desta revisão.

## Correções no servidor LAN

A criação/migração da base SQLite passa a ser serializada entre processos. Bloqueios temporários do journal são repetidos durante um prazo limitado, sem repetir erros de corrupção ou de schema incompatível. A corrida foi reproduzida em dois de 120 arranques simultâneos; após a correção, os 120 passaram, além dos testes de concorrência e bloqueio incluídos na suite.

`certifi==2026.10.19` foi fixado nos três locks, com hashes conferidos no PyPI, após o alerta [GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2). A [versão publicada](https://pypi.org/project/certifi/2026.10.19/) substitui as versões anteriores do bundle de confiança. Esta alteração não desliga verificação de certificados ou nomes; o ensaio TLS real continua a recusar CA desconhecida, hostname errado e fallback HTTP.

Usar o novo digest de imagem e fontes desta entrega para preparar o servidor de teste. As entregas anteriores permanecem como histórico e para conservar a APK/assinatura; os seus locks e imagens não recebem esta correção automaticamente. Fazer backup offline antes de atualizar uma instalação existente. O gerador LAN continua destinado a um dataset novo, sem modificar um estado ativo.

## Falta para WireGuard instalável

1. Adaptador restrito e idempotente do gateway, com configuração pública aprovada, endereços individuais, leitura do estado real e remoção automática de peers. Conservar a diferença entre decisão NOVA, estado observado e remoção pendente quando o gateway está offline.
2. Empacotamento compatível com TrueNAS, fronteira de privilégios, TLS do endpoint remoto e endereçamento/NAT. Não dar ao Control acesso genérico ao shell ou ao Docker socket.
3. Distribuição autenticada dos parâmetros públicos e confiança TLS à TV, bootstrap Directory fora da LAN e renovação. Os parâmetros da fixture não são o protocolo de distribuição final.
4. Catálogo/player pelo túnel, reconexão, suspensão, troca de rede e revogação durante reprodução; depois APK assinada com versão superior e a identidade persistente existente.

Tailscale e NetBird mantêm as próprias provas HTTPS e integração nativa obrigatórias. TrueNAS, Xiaomi Box S2 e Chromecast físicos ainda não foram ensaiados; SEC-01…12 mantém 0/12 aceitações finais. O [roadmap único](ROADMAP_INSTALACAO_SERVER_TV_v0_2.md) conserva esses critérios.
