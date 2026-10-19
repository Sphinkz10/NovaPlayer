# M3 — publicação no Directory através do NOVA Control

> Histórico de incremento. Para o estado, comportamento e instalação atuais, consultar [M3_FECHO.md](M3_FECHO.md). As limitações descritas abaixo referem-se à revisão histórica indicada neste guia.

O proprietário já pode inicializar a identidade, publicar/renovar por uma hora e verificar a publicação no Control. O serviço Directory continua separado; a integração é opcional e está desativada no Compose/gerador TrueNAS por defeito. Não há ainda login Directory na TV, autorização de media ou renovação automática.

## Configuração local de laboratório

Preparar contas e um Directory TLS 1.3 conforme [M3_DIRECTORY_LAB.md](M3_DIRECTORY_LAB.md). Instalar `server/requirements-directory.txt` com `--require-hashes` para correr o Core a partir das fontes. A nova imagem Core também contém estas dependências e o código Directory; isso não inicia o serviço Directory nem publica portas adicionais.

No processo administrativo NOVA Core, configurar estas variáveis antes do arranque:

| Variável | Conteúdo |
|---|---|
| `NOVA_STATE_DIR` | Estado NOVA existente, com proprietário criado |
| `NOVA_DIRECTORY_ORIGIN` | Origem HTTPS IPv4 privada/overlay e porta do Directory |
| `NOVA_DIRECTORY_CA` | Caminho local do certificado/CA público autorizado do Directory |
| `NOVA_CLIENT_ORIGIN` | Origem HTTPS IPv4 privada/overlay da API cliente NOVA que será anunciada |
| `NOVA_CLIENT_CERT` | Caminho local do certificado público dessa API cliente, com SAN correspondente |

Por exemplo, num laboratório no mesmo PC, usar o Directory em `https://127.0.0.1:9443` e um certificado da API cliente para `https://127.0.0.1:8920`. Iniciar o Core por `python -m nova_server.launch`, mantendo a administração em loopback. O endpoint anunciado não é sondado durante o registo; publicar não demonstra que está online ou acessível pela TV.

Em contentores, `127.0.0.1` identifica o próprio contentor. Não copiar estes endereços do ensaio para uma instalação NAS como se ligassem serviços separados. A topologia privada, os mounts de certificados e a execução suportada no NAS exigem validação própria. Este incremento não altera automaticamente o Compose nem o gerador Apps.

## Percurso no painel

1. Entrar no Control com a conta proprietária NOVA.
2. Em «Publicação no Directory», inicializar explicitamente a identidade. A chave privada Ed25519 fica em `directory-signing.key` no estado NOVA; o painel apresenta apenas a impressão digital pública.
3. Introduzir nome do servidor e credenciais da conta Directory proprietária, previamente criada pelo operador. Selecionar «Publicar / renovar por uma hora».
4. «Verificar publicação» volta a autenticar a conta e consulta o Directory. Uma nova operação exige a palavra-passe; não fica guardada para tarefas futuras.
5. Renovar manualmente antes do prazo. A revisão aumenta e a identidade da entrada mantém-se. Se o serviço estiver indisponível, a última observação continua identificada com a sua data; não se transforma num indicador de disponibilidade atual.

A partilha com familiares continua pela CLI Directory. A conta proprietária Directory fica vinculada antes da primeira mutação remota, inclusive quando se perde a resposta. Outra conta não pode substituir essa vinculação pelo painel. A origem Directory também não pode mudar silenciosamente reutilizando o mesmo estado de controlo.

## Proteções e persistência

- Os quatro endpoints `/api/v1/admin/directory*` exigem sessão NOVA proprietária. Dispositivos e contas Directory não são sessões administrativas NOVA.
- O navegador não escolhe URLs, caminhos, certificados ou exceções TLS. Estes valores pertencem à configuração local do operador.
- Corpo limitado, campos adicionais recusados, operações limitadas e erro sem refletir credenciais ou respostas remotas.
- A palavra-passe é apagada do campo antes da chamada e usada apenas durante a operação. Sessões Directory temporárias são encerradas no fim; se o serviço falhar no logout, expiram no Directory. Não existem cookies, localStorage ou sessionStorage para estas credenciais.
- `directory-control.sqlite3`, no estado NOVA, guarda apenas origem, identidade da conta, último registo público assinado e data/resultado da observação. A chave privada está num ficheiro separado, com permissões privadas; em Windows é necessário proteger as ACL do diretório.
- A mesma entrada/chave deve continuar nas renovações; a revisão não pode regredir antes de assinar um novo desafio. Uma chave corrompida não é substituída e uma chave desaparecida após vinculação exige recuperar a original.
- As operações remotas são serializadas na base de controlo, sem manter um bloqueio na base principal NOVA durante os pedidos HTTPS. Uma operação concorrente recebe indicação de ocupado.
- Logout invalida resultados pendentes da UI: uma resposta atrasada não volta a apresentar estado privilegiado.

O backup M2 é offline e inclui os ficheiros dentro do estado NOVA, mas não inclui a base do serviço Directory separado. Este incremento não valida recuperação Directory, rotação de chave ou reversão global de autorizações. Não iniciar renovação automática a partir de uma cópia restaurada.

## Verificar

A partir de `server/`, com dependências de desenvolvimento:

```text
python -m pytest -q tests/test_directory_control.py
python scripts/smoke_directory_control.py --output test-results/directory-control
```

O ensaio usa navegador real, Core administrativo em loopback e Directory real HTTPS TLS 1.3, com contas/certificados descartáveis. Exercita publicação/renovação, palavra-passe errada, mudança de conta recusada, resposta após logout e reinício Core. Em Windows pode usar `--channel msedge` quando Edge estiver instalado. Os ficheiros de estado temporários são removidos e os processos terminam no fim.

Próximo trabalho: descoberta/login na TV, continuidade de confiança TLS e permissões por familiar/biblioteca. A primeira reprodução continua a ser M4; os três túneis nativos permanecem M5.
