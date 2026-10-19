# M3 — critérios únicos de conclusão

Estado: EM EXECUÇÃO. Este documento é o ponto de acompanhamento da M3; os guias anteriores descrevem incrementos históricos, não marcos concluídos.

## Aceitação do software

| Gate | Resultado exigido | Estado |
|---|---|---|
| M3-01 | TV faz login no Directory configurado e só vê servidores autorizados | Pendente |
| M3-02 | Escolha do servidor entrega prova de conta curta, verificável e não reutilizável; aprovação por código liga conta/TV/servidor | Pendente |
| M3-03 | Proprietário atribui bibliotecas ao familiar; NOVA e utilizador Jellyfin limitado recusam acesso fora dessa atribuição | Pendente |
| M3-04 | Reabertura, refresh, mudança de certificado sob a mesma identidade e recusa de regressão/chave alterada | Pendente |
| M3-05 | Revogação de dispositivo/conta impede novas autorizações; isolamento entre contas e entre dois servidores | Pendente |
| M3-06 | Publicação renova sem guardar palavra-passe administrativa; credencial de renovação tem âmbito limitado e é revogável | Pendente |
| M3-07 | Percurso integrado aprovado em Android API 26/35, Linux/Windows e Jellyfin real em Docker; APK e servidor identificados por hashes | Pendente |

Catálogo, player e primeiro filme pertencem à M4. Os três túneis nativos pertencem à M5. Não aumentar o âmbito da M3 com esses módulos.

## Aceitação física

TrueNAS Community, Xiaomi Box S2 e Chromecast: instalação, comando, reboot, ACL e rede reais continuam pendentes. Não há acesso remoto ao NAS disponibilizado nesta sessão. O fecho do software por emuladores/CI e a aceitação física terão resultados distintos, sem anunciar uma prova física que não aconteceu.
