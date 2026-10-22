# M5 — renovação remota e recuperação WireGuard

Este incremento acrescenta duas operações ao perfil de cinco serviços. Os resultados da entrega 0.10 mantêm a sua proveniência histórica em `M5_GATEWAY_CONTENTOR.md`; não demonstram automaticamente este código novo.

## Perfil da TV

A NOVA Cinema pode renovar o perfil pela API HTTPS privada dentro do túnel que está a usar. Antes de guardar a resposta, confirma a associação e a autorização atuais, a validade do perfil anterior e a continuidade da origem, certificado, endereço da TV, chave do gateway, endpoint e rota `/32`. Uma resposta tardia, um destino alterado ou o fim da associação não podem reabrir acesso. Não há troca automática para a LAN.

O botão «Renovar WireGuard pela ligação atual» faz a operação imediatamente. Enquanto o processo e o túnel estão ativos, uma tarefa verifica a cada cinco minutos se restam menos de doze horas e tenta renovar. Falhas conservam apenas o prazo anterior; a tarefa não prolonga o perfil por si própria. O período continua limitado a 24 horas pelo servidor.

**Limite:** se a TV ficar desligada até o perfil expirar, o perfil expirado continua recusado. É necessário prepará-lo novamente pela LAN. Reconexão/descoberta remotas após uma expiração offline continuam pendentes. A primeira associação e aprovação mantêm-se na LAN.

## Cópia cifrada e restauro

`server/scripts/recovery.py` reconhece o formato 3, específico de WireGuard. Os formatos 1 (legado) e 2 (LAN) conservam as suas validações. É necessário parar os cinco serviços e trabalhar numa cópia offline ou através do contentor de manutenção.

```powershell
python server/scripts/recovery.py backup --state CAMINHO_ESTADO_OFFLINE --output nova-wireguard.age --recipient age1DESTINATARIO_PUBLICO --deployment instalar-no-truenas.yaml --services-stopped
python server/scripts/recovery.py restore --input nova-wireguard.age --output RESTAURO_NOVO --identity CHAVE_AGE_PRIVADA --lan-state-root /mnt/POOL/nova-restaurada --image-file servidor/IMAGE.txt --gateway-image-file gateway/IMAGE.txt
```

Usar os binários age verificados da entrega no PATH ou indicar `--age CAMINHO_AGE`. A chave age privada fica separada da cópia e não é incluída no arquivo. Os caminhos acima são exemplos, não valores para colar sem adaptar.

O restauro preserva as identidades NOVA/Directory, certificados e chave/política do gateway. Valida a correspondência das chaves públicas/privadas, dos certificados e das três cópias do segredo do canal. Só aceita o Compose restrito do gerador e digests explícitos para as duas imagens; regenera o YAML para um dataset novo, sem executar comandos provenientes do arquivo.

Sessões, dispositivos, permissões de media, agentes de renovação e inscrições WireGuard são revogados. O segredo do canal local é substituído. Planos, observações, locks e a base de atribuições de IP do gateway não são arquivados: o runtime recuperado começa vazio. As TVs têm de ser novamente associadas/aprovadas; as novas atribuições podem diferir das anteriores. Não é uma migração transparente de sessões.

Seguir `ABRIR_RESTAURO.md` no destino: manter a instalação antiga parada, confirmar permissões/UID/GID e kernel, verificar Jellyfin, republicar no Directory, atribuir bibliotecas, associar/aprovar as TVs e preparar de novo o WireGuard. Rever o endpoint UDP. Atualizar/reiniciar os cinco serviços em conjunto.

## Verificação

- Local: 52 testes de recuperação aprovados, incluindo age real, restauro num destino novo, revogação, cópia adulterada e rejeição de Compose/perfis inconsistentes; bateria completa Windows: 385 aprovados e 8 exclusões POSIX.
- Kotlin: 203 testes; compilação da instrumentação e lint Android aprovados.
- CI adicionada: renovação por HTTPS através do túnel e vídeo após renovação; backup cifrado, restauro dos cinco serviços, ausência de peers antigos e novo túnel/vídeo após associação/aprovação.

Código de validação: `243b8cf8e0cd767f831f3129517980aa7575dc05`; merge CI `c38ca7a7c8b5f9372b29560cfd3809a1521f979a`, com árvores iguais. As alterações posteriores são documentação e inventários.

| Ensaio | Resultado |
|---|---|
| CI principal | 8/8 jobs, incluindo imagem Core, Docker LAN/recuperação, Android e dependências |
| Gateway Docker | 9/9 verificações de túnel e 15/15 de recuperação do formato 3 |
| WireGuard Android API 26 e 35 | 38/38 em cada, incluindo renovação pelo túnel e vídeo posterior |
| Distribuição/update | API 26 e 35 aprovadas |
| Associação/Directory/player LAN | API 26 e 35 aprovadas |

CI: [principal](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39757718554), [gateway e recuperação](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39757718532), [WireGuard](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39757718530), [associação](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39757718505), [distribuição](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39757718558).

Os ensaios iniciais identificaram dois problemas no harness: verificação do cliente antes de terminar o arranque no restauro, e troca entre duas instâncias independentes do motor VPN. O ensaio passou a aguardar todos os papéis e a manter o motor do runtime de produto. A regressão de associação API 26 também recebeu input D-pad real antes da verificação de foco; preserva a confirmação por comando. As execuções anteriores ficam registadas e não são contadas como aprovações.

Imagens por digest, com manifesto acessível sem login:

```text
ghcr.io/sphinkz10/nova-core@sha256:d1d46c2ca598992bf0d6de6af3da05b32242fba036ecf535267623be39667a95
ghcr.io/sphinkz10/nova-gateway@sha256:0b6d479116d8245d8985204cb46090aa9b23737abde40df6720713078b73b5dc
```

APK 0.11: versionCode 11, assinatura persistente idêntica à 0.10, debug desativado, mínimo API 26, quatro ABIs e alinhamento de 16 KB verificados. SHA-256 `febfc8e29e7be3b726c4a5d56ef93a9e22d95ee57be1a025bda8e292d65b741c`. Foi compilada localmente no commit `b81d00b`; os ficheiros da app/core não mudaram até à revisão validada. A CI usa instrumentação debug e identidades temporárias para os ensaios de atualização; não é aceitação física desta APK assinada.

Resultado final: **15/15 jobs aprovados**. [Resultados e proveniência](M5_RENOVACAO_RESULTADOS.json) · [Guia da entrega 0.11](M5_INSTALACAO_WIREGUARD_0_11.md). A pasta local é `NOVA_M5_RENOVACAO_RECUPERACAO_2026-10-22`, com APK assinada, fontes, imagens por digest, ferramentas age, resultados e hashes. As entregas anteriores foram preservadas.

TrueNAS, Xiaomi Box S2 e Chromecast físicos continuam pendentes, tal como Tailscale/NetBird nativos e SEC-01…12. M5 completa permanece aberta.
