# M2 — instalação TrueNAS e recuperação

Estado em 18-10-2026: implementação e ensaios automatizados concluídos na revisão `39fb5874a53ba375a68d54f91bae2b3c64cead3a`, com os oito jobs da [CI 39125165626](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39125165626) aprovados. A imagem publicada passou o ensaio completo de recuperação antes da publicação. O proprietário confirmou que ainda não tem SSH disponível. **Nenhum teste no seu NAS foi executado; a aceitação física M2 permanece pendente.**

## Pacote para Apps

Alvo de empacotamento: TrueNAS Community/SCALE **24.10 ou posterior**, Linux x86_64, com Apps Docker. A versão exata tem de ser registada no ensaio. O gerador recusa versões anteriores, caminhos sobrepostos e UID/GID root. Uma versão aceite pelo gerador não é certificação de compatibilidade.

A CI publica uma imagem `ghcr.io/sphinkz10/nova-core:git-COMMIT` apenas depois de os testes do servidor, dependências e Docker passarem. O artefacto `nova-server-m2-install` contém `IMAGE.txt` com o digest imutável, `SOURCE_COMMIT.txt` e o gerador. Não usar `latest`. A primeira imagem é linux/amd64; Linux arm64 continua a poder ser compilado a partir das fontes, sem validação deste pacote binário.

Digest validado desta entrega (leitura anónima do registry confirmada em 18-10-2026):

```text
ghcr.io/sphinkz10/nova-core@sha256:5ba33012d87746792acc4f220dc3dc7e2985d974e71d7f960028056ea1aca16a
```

No ZIP de instalação, o gerador está diretamente na pasta extraída: usar `python truenas.py ...`. O comando abaixo usa o caminho do pacote de fontes.

1. No TrueNAS, preparar um dataset privado para o estado e duas origens de media separadas. Criar as pastas `nova`, `jellyfin/config` e `jellyfin/cache` dentro do estado. O utilizador/grupo escolhido para os contentores necessita leitura/escrita no estado e leitura/travessia nos media. Aplicar ACL pela interface TrueNAS; não usar `chmod -R 777`, nem alterar as ACL dos filmes indiscriminadamente. Registar o UID/GID real; `568` é apenas exemplo.
2. No PC, gerar o ficheiro para as Apps com Python, substituindo versão, caminhos e imagem pelo digest de `IMAGE.txt`:

   ```text
   python server/scripts/truenas.py --version 25.10.5 --uid 568 --gid 568 --state-root /mnt/POOL/nova-state --media-a /mnt/POOL/filmes --media-b /mnt/POOL/series --image ghcr.io/sphinkz10/nova-core@sha256:DIGEST --output nova-truenas.yaml
   ```

3. Nas Apps, usar **Install via YAML** e colar o conteúdo de `nova-truenas.yaml`. O JSON produzido é um subconjunto válido de YAML. O ficheiro não depende de `.env`, caminhos relativos, build local ou socket Docker. Se o pacote GHCR estiver privado, configurar autenticação de leitura do registry no TrueNAS; não colocar credenciais no YAML nem as enviar à NOVA. A visibilidade pública do pacote depende das definições GitHub do proprietário.
4. A imagem inicializa automaticamente a base NOVA e o código de primeira instalação. Na Shell do contentor `nova-core`, consultar `cat /data/bootstrap.token`; o código não aparece nos logs e deixa de existir depois de criar o proprietário.
5. A administração continua em loopback. Para abrir o Control noutro computador será necessário disponibilizar um túnel administrativo, por exemplo SSH: `ssh -L 8787:127.0.0.1:8787 UTILIZADOR@NAS`, seguido de `http://127.0.0.1:8787`. A instalação pela interface Apps não torna esse endereço acessível no PC por si só. Não há acesso administrativo LAN seguro sem túnel implementado nesta fase.
6. Criar o proprietário no Control; configurar Jellyfin e bibliotecas. Registar ficheiros de teste A/B e contagens. Não abrir portas no router.

Os bind mounts têm `create_host_path: false`: uma origem ausente impede o arranque, em vez de criar uma pasta vazia. Os mounts de media são read-only. Isto não comprova as ACL do teu NAS nem protege contra todas as falhas de armazenamento durante uma execução já iniciada.

Referências: [TrueNAS Apps](https://www.truenas.com/docs/scale/apps/apps/), [Custom Apps 25.04](https://www.truenas.com/docs/scale/25.04/scaleuireference/apps/installcustomappscreens/).

## Cópia cifrada

O backup usa [age](https://github.com/FiloSottile/age), incluído na imagem, com chave X25519. Não é necessário instalar pacotes no sistema base TrueNAS. O backup contém a base NOVA e a configuração/base Jellyfin; exclui filmes, cache, logs e código de bootstrap. O manifesto cifrado guarda a configuração de deployment como referência, sem a executar no restauro.

Esta recuperação M2 aceita **um único utilizador Jellyfin**, o proprietário. Recusa instalações com mais utilizadores porque ainda falta o modelo de recuperação de autorizações de M3. Os scripts recusam schemas desconhecidos; o Core também recusa abrir uma base NOVA de versão futura.

Executar os comandos de manutenção numa máquina Linux com Docker ou na Shell administrativa do TrueNAS, depois de verificar o procedimento na versão instalada. Os exemplos exigem substituição de caminhos e `IMAGEM_POR_DIGEST`; não conceder acesso ao socket Docker ao Core.

Gerar a chave num computador de administração, num diretório privado separado do NAS/backup:

```bash
docker run --rm --network=none --read-only --cap-drop=ALL --user UID:GID -v /CAMINHO/CHAVES:/keys IMAGEM_POR_DIGEST age-keygen -o /keys/nova-recovery.key
docker run --rm --network=none --read-only --cap-drop=ALL --user UID:GID -v /CAMINHO/CHAVES:/keys:ro IMAGEM_POR_DIGEST age-keygen -y /keys/nova-recovery.key
```

Guardar a chave privada num destino separado e protegido. Só o destinatário público `age1...` é usado no backup. Sem a chave privada não é possível recuperar a cópia.

**Parar a App inteira**, Jellyfin e Core, pela interface Apps e confirmar ambos os contentores parados. Em Compose de laboratório: `docker compose stop`. O script de backup exige a confirmação explícita `--services-stopped`; não consulta o Docker nem consegue provar esse estado sozinho. Não executar sobre bases em utilização. Guardar o YAML de deployment fora dos diretórios de estado.

```bash
docker run --rm --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges --user UID:GID -v /mnt/POOL/nova-state:/state:rw -v /mnt/POOL/backups:/backups:rw -v /CAMINHO/nova-truenas.yaml:/deployment.yaml:ro IMAGEM_POR_DIGEST python scripts/recovery.py backup --state /state --output /backups/nova-AAAA-MM-DD.age --recipient age1DESTINATARIO --deployment /deployment.yaml --services-stopped
```

O estado fica montado em leitura/escrita para o SQLite verificar e consolidar journals com os serviços parados. A ferramenta nunca inclui a chave privada. Não substitui uma cópia com o mesmo nome. Reiniciar a App depois da cópia, mesmo se o backup falhar; verificar o resultado antes de a considerar utilizável. Copiar o ficheiro `.age` para outro dispositivo protege também contra perda do NAS.

## Restauro ensaiável e sem sobreposição

Manter a App parada. Criar um diretório pai privado vazio no destino de recuperação. A subpasta `ensaio` **não pode existir**. A chave privada é montada apenas durante esta operação:

```bash
docker run --rm --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges --user UID:GID -v /CAMINHO/BACKUPS:/backups:ro -v /CAMINHO/CHAVES:/keys:ro -v /mnt/POOL/recuperacao:/restore:rw IMAGEM_POR_DIGEST python scripts/recovery.py restore --input /backups/nova-AAAA-MM-DD.age --output /restore/ensaio --identity /keys/nova-recovery.key
```

O resultado aparece em `ensaio/state`. O original permanece intacto. Arquivos alterados, incompletos, com caminhos fora do destino, links ou membros duplicados são recusados. O restauro invalida **todas as sessões NOVA, dispositivos/tokens Jellyfin e chaves API Jellyfin**; é obrigatório novo login. O proprietário e a identidade Jellyfin mantêm-se; as observações antigas de saúde são removidas e a cache é recriada.

Gerar um YAML novo apontado a `ensaio/state`, usando inicialmente **a mesma imagem/digest e versão Jellyfin da cópia**. Rever `deployment.original.txt` apenas como referência. Aplicar ACL à pasta restaurada pelo TrueNAS. Iniciar apenas uma instalação de cada vez, devido às mesmas portas e identidade; entrar com o proprietário e verificar novamente os ficheiros A/B. A recuperação não restaura media apagados nem substitui backups dos datasets de filmes.

## Atualização e reversão

1. Parar ambos os serviços e produzir uma cópia cifrada; guardar o YAML e os digests atuais.
2. Substituir apenas o digest Core pela revisão testada, mantendo diretórios e credenciais. Mudanças Jellyfin devem ser ensaiadas separadamente.
3. Iniciar e verificar saúde, identidade, login, bibliotecas e contagens. O ensaio automatizado cobre recriação dos contentores e migração aditiva do schema NOVA original (0) para 1.
4. Se falhar, parar e restaurar a cópia numa pasta nova com os digests antigos. Não executar uma imagem antiga sobre uma base já migrada sem compatibilidade demonstrada.

Não existe ainda migração automática de qualquer versão futura de Jellyfin, nem atualização automática das imagens.

## Recolher evidência da instalação

Depois de os healthchecks ficarem saudáveis, consultar os nomes/IDs dos dois contentores na interface Apps e executar na Shell administrativa:

```text
python3 server/scripts/acceptance.py --core-container NOME_CORE --jellyfin-container NOME_JELLYFIN --output verificacao-nas.json
```

O relatório regista imagens, saúde, portas loopback, utilizador não root e mounts read-only. Não inclui variáveis de ambiente ou credenciais. Mesmo com todos esses checks aprovados, `physical_acceptance_complete` permanece falso: reinício, indexação e recuperação precisam de resultados próprios. As licenças age/Go e módulos compilados acompanham a imagem em `/usr/share/nova/licenses/`.

## Aceitação física necessária para fechar M2

Registar versão/build TrueNAS, CPU, UID/GID, ACL e digests; instalar pelas Apps; concluir o Control; indexar A/B; demonstrar escrita bloqueada com ficheiros descartáveis; reiniciar o NAS; ensaiar origem ausente; backup/restauro com novo login e tokens anteriores rejeitados; atualização/reversão; medir espaço e recursos. Não usar tentativas de escrita nos filmes de produção.

Sem este registo, M2 tem implementação e prova Docker, mas **não está validada no TrueNAS do proprietário**. Não marcar esse gate como aprovado por equivalência.
