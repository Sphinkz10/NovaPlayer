# M3 — Directory privado, primeiro serviço executável

O Directory já tem um serviço de laboratório independente: contas, sessões, registo de servidores com prova de posse de chave Ed25519, descoberta por conta, partilha explícita e revogação. Não está integrado no ecrã da TV nem no assistente NOVA Control. Não fecha a M3 nem disponibiliza login universal na APK atual.

## O percurso implementado

1. O operador cria contas locais do Directory pela CLI; não existe signup público. Palavras-passe Argon2id, limites de tentativas e duas verificações simultâneas por processo.
2. O proprietário inicializa explicitamente uma chave de assinatura no estado do NOVA Server, após a criação do proprietário NOVA. A chave privada fica nesse estado e não é enviada ao Directory.
3. Faz login no Directory por HTTPS TLS 1.3, pede um desafio e assina o pedido com a chave do servidor. O desafio liga conta, Directory, servidor, chave, origem/certificado públicos, versão e prazos.
4. O Directory verifica a assinatura e consome o desafio numa transação SQLite. Dura 60 segundos; uma submissão inválida também o consome. Inscrições concorrentes e provas antigas não substituem uma revisão mais recente.
5. O proprietário vê os seus servidores e pode autorizar outra conta existente a descobri-los. Outras contas não veem os registos. A autorização é apenas para descoberta: não cria sessão NOVA nem concede acesso a Jellyfin/media.
6. A publicação dura uma hora. Renovar exige um novo desafio e a mesma chave. Pode publicar novo certificado sob essa chave; a APK atual ainda não consome essa renovação. A substituição da chave não é automática.

A identidade da entrada é própria e vinculada à conta do proprietário. Duas contas podem publicar o mesmo UUID NOVA nos seus espaços, mas não podem alterar os registos uma da outra. A assinatura prova posse da chave de registo; não prova que o endpoint está online nem constitui uma certificação independente de propriedade do NAS. O cliente ainda terá de validar a identidade TLS e obter autorização NOVA.

## Fronteiras e limites

- Serviço e base `directory.sqlite3` separados do NOVA Core e Jellyfin. Não são iniciados pelo Compose/gerador TrueNAS nem incorporados na imagem NOVA Core existente.
- Launcher limitado a `127.0.0.1`, sem proxy headers nem access logs. HTTPS TLS 1.3 obrigatório; sem HTTP, redirecionamentos, `verify=False` ou alteração da trust store do sistema.
- Contas de laboratório independentes da conta NOVA. Sessões de 15 minutos, apenas hashes no Directory, máximo de oito por conta; logout e desativação invalidam autorização.
- Descriptor admite apenas versão, UUID, nome, origem HTTPS IPv4 privada/overlay e certificado público com SAN correspondente. Não aceita campos de biblioteca, histórico, tokens Jellyfin ou chaves VPN. Nenhum pedido ao endpoint publicado é feito pelo Directory.
- Metadados públicos de identidade, nome e endereço privado ficam legíveis na base do Directory. As assinaturas não os cifram. A descoberta exige sessão de uma conta autorizada; não há pesquisa global nem listagem pública de contas.
- Limites de laboratório: 100 contas criadas pelo operador, 20 entradas por proprietário/200 globais, 8 desafios pendentes por proprietário/256 globais, 50 membros por servidor e 50 partilhas recebidas por conta. Entradas removidas mantêm uma reserva de identidade para impedir reativação por provas antigas; continuam a contar para o limite.
- Retirar uma partilha impede novas consultas autorizadas. Não apaga endereços já conhecidos nem revoga uma sessão NOVA anteriormente aprovada. A revogação de media/VPN continua a depender dos respetivos serviços.
- A confiança inicial no Directory depende do certificado/CA configurado pelo operador. A assinatura do servidor acrescenta integridade e continuidade de chave; não protege a primeira consulta contra um Directory comprometido que apresente outra chave. Ainda não há transparência de chaves, recuperação, rotação da chave de assinatura ou federacão.
- A CLI de descoberta valida assinatura, audiência, prazo e certificado. A persistência de pins/versões por dispositivo e a política contra regressões após cache pertencem à integração Android seguinte. Não converter automaticamente uma resposta do Directory em confiança cega na TV.

## Ensaiar no PC

A partir de `server/`, num ambiente Python 3.12/3.13:

```text
python -m pip install --require-hashes -r requirements-dev.txt
python -m pytest -q tests/test_directory.py
python scripts/smoke_directory_tls.py --output test-results/directory
```

O segundo ensaio gera contas, certificados e chaves descartáveis, inicia um processo HTTPS real, regista um NOVA inicializado, verifica isolamento/partilha, reinício, renovação e revogação. Recusa CA desconhecida, hostname errado e TLS 1.2. No fim remove os dados descartáveis e termina o processo. Não contacta o NAS nem as TVs e não grava palavras-passe/tokens nos relatórios.

Para usar manualmente a CLI, instalar apenas `requirements-directory.txt` com `--require-hashes`. Preparar um diretório de estado privado fora do Git e certificado/chave TLS locais com SAN IP `127.0.0.1`. Em Windows, conferir que as ACL restringem esse diretório à conta operadora; `chmod` não substitui ACL Windows.

```text
python -m nova_directory account-add --state CAMINHO_DIRECTORY --origin https://127.0.0.1:9443 --username owner
python -m nova_directory account-add --state CAMINHO_DIRECTORY --origin https://127.0.0.1:9443 --username familiar
python -m nova_directory serve --state CAMINHO_DIRECTORY --origin https://127.0.0.1:9443 --certificate DIRECTORY_PUBLICO.pem --key DIRECTORY_PRIVADO.key
```

As palavras-passe são pedidas com `getpass`, nunca em argumentos, ficheiros de exemplos ou mensagens de erro. O processo `serve` fica ativo no terminal escolhido pelo operador.

Noutro terminal, usar o estado de um NOVA Server de laboratório já inicializado e o certificado público da sua API cliente:

```text
python -m nova_directory.client key-init --state CAMINHO_ESTADO_NOVA
python -m nova_directory.client register --directory https://127.0.0.1:9443 --ca DIRECTORY_PUBLICO.pem --username owner --state CAMINHO_ESTADO_NOVA --client-origin https://127.0.0.1:8920 --certificate NOVA_CLIENTE_PUBLICO.pem --name Casa
python -m nova_directory.client share --directory https://127.0.0.1:9443 --ca DIRECTORY_PUBLICO.pem --username owner --entry ID_DEVOLVIDO --member familiar
python -m nova_directory.client discover --directory https://127.0.0.1:9443 --ca DIRECTORY_PUBLICO.pem --username familiar
```

`register` devolve a identidade da entrada e o prazo. Repetir antes de uma hora para renovar; ainda não existe agente de renovação automática. `unshare` retira a partilha; `remove` desativa a entrada. `account-disable`, no operador local, termina a utilização da conta e oculta dos membros os registos pertencentes a essa conta.

`key-init` não substitui uma chave existente ou corrompida. `register` recusa criar uma nova silenciosamente. A chave fica em `directory-signing.key` dentro do estado NOVA: preservar esse estado e incluí-lo nas cópias cifradas. A base separada do Directory não é incluída pela ferramenta de recuperação M2; ainda não existe procedimento validado de recuperação Directory que preserve revogações. Não restaurar uma cópia antiga como se isso garantisse continuidade de autorizações.

## Próximo incremento

Ligar registo/renovação ao Control, implementar login/descoberta e continuidade de confiança na TV e ligar a autorização às contas/bibliotecas Jellyfin. Depois M4: catálogo e primeiro filme. A aceitação física TrueNAS/Xiaomi/Chromecast e os três percursos VPN completos permanecem pendentes.

## Evidência de 19-10-2026

Revisão funcional `1f7757168da12e5fe68b543bc807b1ab33492a07`: [CI do servidor](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39260515012). Python 3.12 e 3.13 aprovados em Linux (204 testes) e Windows (198 aprovados, seis específicos de POSIX ignorados). Inclui 42 testes Directory e 16 verificações do percurso HTTPS real em cada combinação. HTTP, associação HTTPS, navegador e Compose/recuperação também aprovados. Análise das dependências Python de produção e Directory sem vulnerabilidades conhecidas reportadas nessa execução.

A primeira execução revelou uma ligação SQLite de leitura que não era fechada explicitamente, impedindo a limpeza em Windows/Python 3.13. A revisão acima corrige o ciclo de vida da ligação e inclui regressão que mantém referências às ligações para não depender do garbage collector. Os resultados de Linux não foram usados para ocultar essa falha em Windows.

Estes resultados validam o serviço e a CLI em laboratório. Não demonstram descoberta na TV, media, VPN, recuperação Directory ou segurança final da plataforma.

Primitiva utilizada: [Ed25519 em PyCA cryptography](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/). O protocolo próprio é de laboratório; não se apresenta como OAuth/OIDC nem como validação final de segurança.
