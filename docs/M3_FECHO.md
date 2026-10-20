# M3 — critérios únicos de conclusão

**Estado: M3 CONCLUÍDA NO SOFTWARE DE LABORATÓRIO — 20-10-2026.** Os sete critérios abaixo passaram. TrueNAS e TVs físicos continuam sem ensaio. Este é o ponto único de acompanhamento; os guias anteriores preservam incrementos históricos.

## Aceitação do software

| Gate | Resultado exigido | Estado |
|---|---|---|
| M3-01 | TV faz login no Directory configurado e só vê servidores autorizados | Aprovado |
| M3-02 | Escolha do servidor entrega prova de conta curta, verificável e não reutilizável; aprovação por código liga conta/TV/servidor | Aprovado |
| M3-03 | Proprietário atribui bibliotecas ao familiar; NOVA e utilizador Jellyfin limitado recusam acesso fora dessa atribuição | Aprovado |
| M3-04 | Reabertura, refresh, mudança de certificado sob a mesma identidade e recusa de regressão/chave alterada | Aprovado |
| M3-05 | Revogação de dispositivo/conta impede novas autorizações; isolamento entre contas e entre dois servidores | Aprovado |
| M3-06 | Publicação renova sem guardar palavra-passe administrativa; credencial de renovação tem âmbito limitado e é revogável | Aprovado |
| M3-07 | Percurso integrado aprovado em Android API 26/35, Linux/Windows e Jellyfin real em Docker; APK e servidor identificados por hashes | Aprovado |

Catálogo, player e primeiro filme pertencem à M4. Os três túneis nativos pertencem à M5. Não aumentar o âmbito da M3 com esses módulos.

## Evidências e pacote

Revisão executável: `33346c41109062077b2339fc2711e6de44f0dad2`, na branch `codex/phase-one`, [PR #1 em rascunho](https://github.com/Sphinkz10/NovaPlayer/pull/1). O fecho técnico não implica merge ou lançamento para famílias.

| Prova | Resultado |
|---|---|
| [CI principal 39344143882](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39344143882) | 8/8 jobs aprovados, incluindo repetição Docker da imagem exata antes de publicar |
| Python 3.12 e 3.13, Linux | 257 testes aprovados em cada combinação |
| Python 3.12 e 3.13, Windows | 251 aprovados + 6 específicos de POSIX ignorados em cada combinação |
| Núcleo Kotlin | 203 testes aprovados; build e lint Android aprovados |
| [Android 39344143896](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39344143896) | API 26 e 35: 11 etapas M3 + 11 regressões de associação em cada emulador |
| Jellyfin real Docker | 13 verificações M3: duas contas/utilizadores restritos, isolamento de bibliotecas/servidores, âmbito, replay e revogação |
| Control no navegador | 9 verificações de permissões e aprovação + 15 do Directory, nas quatro combinações Linux/Windows/Python |
| Distribuição | ZIPs de CI verificados pelos seus digests; APK conferida contra o relatório, assinatura v2 válida; manifesto da imagem conferido no registry com leitura anónima |

O Android usa um Jellyfin HTTP simulado isolado; o ensaio Docker separado usa o Jellyfin real. A prova envolve duas identidades NOVA e uma instância Jellyfin; não equivale a dois NAS físicos. A primeira tentativa final do API 26 falhou ao atribuir foco ao botão na instrumentação legada (`DevicePairingInstrumentation:130`), antes da associação. O mesmo código foi repetido e concluiu as 22 etapas. Esta instabilidade do ensaio fica registada; o comando físico ainda precisa de aceitação.

APK entregue: `NOVA-M3-0.6-lab.apk`, pacote `com.novacinema.connect.poc`, versão `0.6-m3-lab`/6, mínimo API 26, target 35; ABIs arm64-v8a, armeabi-v7a, x86 e x86_64. É a APK exata da prova API 35. Cada job usa uma assinatura debug própria; a APK API 26 é outro binário e o respetivo hash permanece no relatório.

```text
APK SHA-256: f48221112870369756405a22e7c7c099eb9855a5c79351157b9f6b5e9593235d
Imagem NOVA Core (linux/amd64):
ghcr.io/sphinkz10/nova-core@sha256:9d916c138529cfc60dab38565f3d5d1fb216ee7dbe7af442a224c35cd687352b
```

O servidor mantém o identificador de desenvolvimento `0.3.0-dev`; o digest e a revisão acima identificam este marco. Para instalar esta revisão, usar esta imagem nos comandos M2. A imagem e o digest antigos no guia histórico identificam a entrega M2.

A pasta de entrega local `NOVA_M3_2026-10-20` reúne `ABRIR_PRIMEIRO.md`, APK, fontes, gerador TrueNAS, imagem por digest e evidências. `M3_RESULTADOS.json` identifica commits e artefactos; `SHA256SUMS.txt` permite conferir os ficheiros. As fontes incluem a documentação consolidada posterior aos testes, com o código executável da revisão indicada acima.

## Aceitação física

TrueNAS Community, Xiaomi Box S2 e Chromecast: instalação, comando, reboot, ACL e rede reais continuam pendentes. Não há acesso remoto ao NAS disponibilizado nesta sessão. O fecho do software por emuladores/CI e a aceitação física terão resultados distintos, sem anunciar uma prova física que não aconteceu.

## Percurso entregue pela M3

1. O operador mantém o Directory separado, cria as contas e partilha a entrada do servidor. O proprietário publica a identidade a partir do Control.
2. A app tem um bootstrap público do Directory, instalado pelo proprietário. O familiar entra com a própria conta e só recebe os servidores partilhados com ela.
3. Ao escolher um servidor, recebe uma prova Ed25519 válida por 90 segundos, ligada à conta, entrada e UUID NOVA. O Core consome-a uma vez. O proprietário consulta o código e a conta verificada no Control.
4. Em **Permissões dos familiares**, atribui uma ou duas bibliotecas e fornece as credenciais administrativas Jellyfin apenas para essa operação. A NOVA cria um utilizador restrito e guarda o token cifrado no servidor. Nenhum token Jellyfin é entregue à TV.
5. Consulta novamente o código e aprova. A TV confirma a identidade e mostra os nomes das bibliotecas atribuídas. Ainda não lista nem reproduz filmes.
6. Reabertura/refresh mantêm a conta; revogar dispositivo ou conta bloqueia novas autorizações. Uma renovação TLS é aceite através de novo registo assinado pela mesma chave, com versão crescente. Chave alterada ou regressão ficam bloqueadas.

A partilha Directory permite descoberta e novas provas de conta. Retirá-la não revoga uma sessão NOVA já aprovada: usar **Revogar conta e dispositivos** no Control para retirar esse acesso. Não prometer apagar endereços já conhecidos.

A publicação dura uma hora. O Core verifica a renovação a cada 60 segundos e tenta renovar nos últimos 15 minutos. A credencial tem âmbito exclusivo de renovação da entrada, validade de 30 dias e fica cifrada no estado NOVA; a palavra-passe Directory não fica guardada. Ao expirar a credencial é necessário publicar de novo com a conta do proprietário. Falha de rede não deve ser confundida com publicação renovada: consultar a data e o prazo no Control.

## Ensaio instalável de laboratório

O servidor M2 pode ser ensaiado em Docker/TrueNAS de teste com o [procedimento M2](M2_TRUENAS_RECUPERACAO.md). A jornada M3 ainda usa processos separados e loopback; o Compose e o gerador Apps não expõem automaticamente Directory/API cliente à LAN. Não é uma instalação familiar pronta. Sem acesso administrativo ao NAS, pode-se ensaiar a M3 num PC de teste.

Preparação no PC, a partir de `server/`:

1. Instalar `requirements-directory.txt` com `pip install --require-hashes -r requirements-directory.txt`. Usar um estado NOVA já inicializado e Jellyfin configurado, em diretórios privados fora do Git.
2. Preparar dois pares TLS locais válidos, um para Directory e outro para API cliente, com SAN IP `127.0.0.1`. Não reutilizar as chaves descartáveis dos testes nem distribuir chaves privadas.
3. Criar as contas pelo operador e iniciar o Directory (as palavras-passe são pedidas no terminal):

   ```text
   python -m nova_directory account-add --state ESTADO_DIRECTORY --origin https://127.0.0.1:9443 --username owner
   python -m nova_directory account-add --state ESTADO_DIRECTORY --origin https://127.0.0.1:9443 --username familiar
   python -m nova_directory serve --state ESTADO_DIRECTORY --origin https://127.0.0.1:9443 --certificate DIRECTORY_PUBLICO.pem --key DIRECTORY_PRIVADO.key
   ```

4. No processo Control, definir `NOVA_DIRECTORY_ORIGIN=https://127.0.0.1:9443`, `NOVA_DIRECTORY_CA` com o caminho absoluto do certificado público Directory, `NOVA_CLIENT_ORIGIN=https://127.0.0.1:8920` e `NOVA_CLIENT_CERT` com o certificado público cliente. Reiniciar o Control mantendo `NOVA_STATE_DIR` e `NOVA_JELLYFIN_URL` corretos. No Control, inicializar identidade e publicar com a conta Directory proprietária.
5. Noutro terminal, definir o mesmo `NOVA_STATE_DIR`, `NOVA_JELLYFIN_URL`, `NOVA_CLIENT_ORIGIN`, `NOVA_CLIENT_CERT` e `NOVA_CLIENT_KEY`; executar `python -m nova_server.client_api`.
6. Partilhar a entrada (ID mostrado no Control) e exportar o bootstrap público:

   ```text
   python -m nova_directory.client share --directory https://127.0.0.1:9443 --ca DIRECTORY_PUBLICO.pem --username owner --entry ID_ENTRADA --member familiar
   python scripts/directory_profile.py --origin https://127.0.0.1:9443 --certificate DIRECTORY_PUBLICO.pem --output nova-directory.json
   ```

   O exportador valida TLS 1.3, hostname, certificado exato e chave pública do emissor; recusa sobrescrita. O JSON contém apenas configuração pública. Recebê-lo por um canal do proprietário é a confiança inicial; não aceitar um bootstrap fornecido por desconhecidos.
7. Instalar a APK debug num aparelho de teste com ADB previamente autorizado. Usar sempre `-s SERIAL` para selecionar o aparelho. A APK de distribuição não inclui o Directory particular do utilizador. No PowerShell:

   ```powershell
   adb -s SERIAL install -r NOVA-M3-0.6-lab.apk
   adb -s SERIAL shell run-as com.novacinema.connect.poc mkdir -p files
   Get-Content -Raw -Encoding utf8 nova-directory.json | adb -s SERIAL shell -T run-as com.novacinema.connect.poc tee files/nova-directory.json
   adb -s SERIAL reverse tcp:9443 tcp:9443
   adb -s SERIAL reverse tcp:8920 tcp:8920
   ```

   Alternativa de build para incluir a configuração pública no APK: `gradlew.bat :app:assembleDebug -PnovaDirectoryProfile=CAMINHO_ABSOLUTO_JSON`. Uma compilação própria não é o mesmo binário ensaiado na CI. A assinatura debug também pode diferir: não desinstalar uma instalação existente sem aceitar perder os seus dados locais.
8. Abrir **Entrar na NOVA · Directory**, entrar como familiar, escolher o servidor e seguir o percurso de atribuição/aprovação acima. Fechar/reabrir a app, verificar bibliotecas e revogar no Control. No fim remover os redirecionamentos com `adb -s SERIAL reverse --remove tcp:9443` e o equivalente para `8920`.

Este ensaio por ADB exige que o PC consiga alcançar os serviços e que o aparelho suporte ADB reverse. Não foi executado nas boxes físicas. As contas NOVA proprietária, Directory e Jellyfin são independentes; só a conta do familiar entra na TV.

## Dados, atualização e limites

Schema NOVA 3; migração preserva proprietário/configuração. Fazer backup offline cifrado antes de atualizar. Não executar a versão M2 antiga sobre schema 3: para regressar, restaurar a cópia compatível numa pasta nova. A recuperação preserva identidades mas invalida sessões, pedidos, provas usadas, permissões e credencial de renovação; o proprietário tem de reconfigurar permissões e republicar. A base Directory separada não faz parte do backup M2 e não tem ainda um procedimento de recuperação validado.

Assinaturas não tornam o Directory independente de confiança na primeira consulta. Bootstrap e emissor são fixados pelo proprietário; pins/versões posteriores são autenticados pelo Keystore. Ainda não há federação, transparência de chaves, recuperação/rotação da chave Directory, signup público ou exposição na Internet. SEC-01…12 continuam sem validação final.

Android API 26 usa Conscrypt 2.7.0 por ligação para TLS 1.3, sem substituir o fornecedor global. Ed25519 usa Bouncy Castle 1.86. Dependências e hashes estão fixados; fontes: [Conscrypt](https://github.com/google/conscrypt), [Bouncy Castle](https://www.bouncycastle.org/download/bouncy-castle-java/).
