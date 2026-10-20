# M5 — Serviço WireGuard e estado observado no Control

Incremento posterior ao [adaptador restrito](M5_GATEWAY_WIREGUARD.md). Acrescenta um processo Linux independente, atribuições de IP duráveis e um canal local autenticado. A configuração da rede do NAS e o instalador TrueNAS continuam por implementar. A entrega LAN assinada 0.9 permanece disponível sem este componente.

## Comportamento implementado

1. Quando explicitamente configurado, um único processo Core publica planos públicos a cada dois segundos num diretório privado. Cada plano tem identificadores novos, o servidor esperado, a lista aprovada e validade até 15 segundos. Contas desativadas e TVs revogadas/expiradas deixam de constar da lista.
2. O processo `python -m nova_server.gateway_service --config /caminho/privado/gateway.json` lê o canal a cada segundo. Valida HMAC-SHA256, estrutura, prazo, relógio monotónico e identidade. Os planos não fornecem comandos, interfaces, endereços ou chaves privadas; as observações devolvem os endereços privados /32 lidos do kernel, sem credenciais.
3. Uma base SQLite separada guarda a política local e as atribuições `/32` por identidade/chave pública. A transação é confirmada antes da aplicação no kernel. Reiniciar o processo ou reconstruir o conjunto de peers conserva os endereços das TVs ainda aprovadas. Revogadas deixam de reservar endereços.
4. O adaptador verifica o namespace, alias NOVA, chave pública e endereço do gateway. Remove peers desconhecidos e permissões de rede excessivas, aplica os `/32` guardados e confere o kernel. Repetir sem alterações não escreve novamente no WireGuard.
5. O worker escreve uma observação autenticada, associada ao plano. O Core só a aceita se pertencer à sua execução atual, continuar dentro do prazo monotónico e corresponder às aprovações atuais. Revogar uma TV invalida imediatamente a observação no Control, mesmo antes da próxima aplicação no kernel.
6. O Control distingue `configuration_observed` de ausência de observação válida. Mostra o instante observado e retira a indicação no fim do prazo. `handshake_verified=false` e `remote_access_enabled=false` continuam explícitos. A API da TV ainda não recebe parâmetros de ligação remota.

O diretório de canal e os ficheiros têm permissões POSIX `0700`/`0600`. Planos e observações usam assinaturas HMAC com separação de papel; os ficheiros são substituídos atomicamente. O segredo aleatório de 32 bytes é local, separado e nunca é uma sessão administrativa. Não é uma chave WireGuard. As duas entidades locais e o operador são confiáveis; este canal não se destina a pares remotos hostis.

Há locks de processo exclusivos para publisher e worker. Só o worker host precisa de root para entrar no namespace Linux já provisionado. O Core mantém todas as capabilities removidas, sem Docker socket, rede host ou privilégios de administração de rede. O endurecimento/empacotamento do worker é um gate do instalador, não uma propriedade já validada em TrueNAS.

## Arranque de desenvolvimento Linux

Requer um namespace dedicado previamente criado pelo operador, com nome `nova-wg-…`, interface WireGuard UP, alias `nova-wireguard-v1:<server_id>`, chave pública exata e apenas o endereço privado do gateway em `/32`. Rotas, firewall e a chave privada do gateway são provisionados fora deste serviço. Não aplicar a uma VPN partilhada.

O exemplo [gateway.example.json](../server/gateway/gateway.example.json) deve ser copiado para um ficheiro local `0600`, preenchido com a identidade NOVA e a chave **pública** já existente. O placeholder é inválido de propósito. Os diretórios de canal e leases devem ser separados e `0700`; o canal pertence ao UID do Core e a base de leases ao worker host. O worker root consegue substituir as observações mantendo a propriedade do diretório do Core.

Criar uma vez um segredo binário aleatório de 32 bytes, num ficheiro `0600`, legível apenas pelo Core e pelo worker root. Não guardar esse ficheiro nas fontes, num rascunho Control ou num log. Conservar a base `leases.sqlite3` quando reconstruir o namespace; se a política/identidade não corresponder, o serviço recusa reutilizá-la.

No Core, definir `NOVA_WIREGUARD_CHANNEL_DIR` e `NOVA_WIREGUARD_CHANNEL_KEY_FILE` com os caminhos locais. Usar apenas um processo Core por canal. O [overlay Compose explícito](../server/gateway/compose.channel.yaml) monta o diretório e o segredo, este só de leitura; não altera privilégios ou portas. Requer fontes/imagem que incluam este incremento e os binds já preparados. O Compose normal permanece com o canal desativado.

No host Linux de desenvolvimento, com as dependências Python do servidor instaladas e a configuração pronta:

```sh
cd /caminho/NovaPlayer/server
python -m nova_server.gateway_service --config /caminho/privado/gateway.json
```

A consulta `GET /api/v1/admin/connect/wireguard/gateway` exige sessão de proprietário. Não existe API HTTP de execução, instalação ou alteração da política do host. O endpoint de plano administrativo anterior continua só de leitura.

## Falhas e recuperação

Transporte ausente, adulterado, expirado ou incompatível provoca uma tentativa de remoção dos peers apenas na interface que ainda passe a verificação de propriedade/identidade. Falhas de escrita/leitura do kernel também invalidam a observação. Se não for possível confirmar a remoção, o relatório diz `cleanup_confirmed=false`; nunca anuncia sucesso. SIGTERM/SIGINT e a saída normal tentam remover e conferir os peers. Ao parar normalmente, o Core retira o plano, sem apagar as atribuições de IP guardadas.

O kernel WireGuard não expira peers por si próprio. SIGKILL, perda do processo/host ou gateway inacessível podem conservar peers até à recuperação do worker ou destruição do namespace. O Control deixa de aceitar a observação após o prazo, mas isso não remove um peer do kernel. Falta ao instalador/supervisor garantir o ciclo de vida e a remoção do namespace perante falhas abruptas. Ainda não se pode fechar a M5 ou as validações finais de segurança.

## Validação

Testes locais de Windows: serviço/canal com backend controlado, persistência de IPs, reinício, assinatura inválida, troca de papel, expiração, revogação, relógio monotónico, política incompatível, falha de readback e fronteira proprietário/TV. Os testes POSIX de permissões/locks e ciclo de vida real do Core correm em Linux.

A prova nativa passa a lançar o worker como processo separado em Linux, com publisher real do Core, aprovação HTTP e cliente Android. Verifica observação no Control, reinício/limpeza do worker, conservação do `/32`, repetição sem escritas, handshake, HTTPS, firewall e remoção por revogação. Resultados: **29/29 verificações em cada API 26 e 35**, com handshake real. API 26: RX 8452 B / TX 8700 B; API 35: RX 8340 B / TX 8700 B; 6 descartes do firewall em cada ensaio. Código `9dffd36aa3249d8309f7d21f97afe5359351e8b0`, merge CI `1ac5c352add9798b3887d354829d23d2e2794715`, com árvores iguais. Servidor: **369/369 em Linux**, **361 aprovados + 8 exclusões POSIX em Windows**. CI principal: **8/8 jobs**, incluindo Docker, Android build/lint, dependências e imagem. Associação/player e distribuição/update API 26/35 também aprovados. O job Windows/Python 3.13 foi repetido após o ensaio de navegador atingir o prazo de 5 segundos enquanto aguardava a configuração de permissões Jellyfin, antes da interação WireGuard; a repetição conservou código e verificações. Os restantes jobs passaram na primeira tentativa. [Relatório e proveniência](M5_SERVICO_RESULTADOS.json).

## Próximos gates

- Provisionamento/instalador do namespace, firewall, serviço e supervisor compatíveis com TrueNAS Community, sem instruir o utilizador a modificar o sistema base do NAS.
- Entrega autenticada dos parâmetros públicos à TV e catálogo/player através do túnel.
- Jornadas nativas completas Tailscale e NetBird.
- Aceitação física TrueNAS/Xiaomi Box S2/Chromecast e SEC-01…12.
