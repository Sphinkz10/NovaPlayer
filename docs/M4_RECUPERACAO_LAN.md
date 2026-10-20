# M4 — Recuperação integrada LAN

Implementação em validação. A entrega anterior de instalação LAN continua preservada. Este guia cobre o novo formato 2 de backup/restauro; o formato legado M2 continua suportado separadamente.

## O que fica protegido

A cópia inclui NOVA, configuração Jellyfin, Directory, identidades de assinatura, chave de credenciais e os três certificados/chaves TLS. Media, cache, logs, token de bootstrap, chave privada da CA offline e chave privada age ficam fora da cópia. O estado é cifrado por age X25519 com integridade autenticada. Guardar a chave privada age separadamente do arquivo; a chave da CA offline também precisa de guarda própria.

Parar **os quatro serviços** antes de copiar/arquivar. A confirmação `--services-stopped` é dada pelo operador; a ferramenta não controla o NAS nem verifica remotamente o estado das Apps. Não instalar Python/age no sistema base do TrueNAS: usar uma cópia offline no PC ou a imagem NOVA de manutenção, que já inclui age.

O backup reconhece o perfil LAN automaticamente. Verifica a consistência das bases, proprietário, identidades, chaves e certificados. Uma identidade em falta ou diferente provoca recusa; não é gerada uma substituta. O YAML tem de corresponder ao perfil do gerador NOVA. Configurações Docker arbitrárias são recusadas.

## Cópia offline no PC

Usar o projeto completo desta entrega e Python 3.12/3.13 com as dependências `server/requirements-directory.txt`. Para age no Windows, obter a versão 1.3.2 na [release oficial](https://github.com/FiloSottile/age/releases/tag/v1.3.2); o exemplo pressupõe `age.exe` e `age-keygen.exe` disponíveis no PATH. Também se pode indicar o caminho de `age.exe` com `--age`.

1. Atualizar os três serviços NOVA para a imagem por digest desta entrega, conservando os datasets e identidades existentes. Não voltar a executar o assistente de instalação numa instalação já configurada.
2. Parar a App inteira nas Apps do TrueNAS. Transferir por um método administrativo privado o estado parado para `COPIA_OFFLINE`, preservando a estrutura `nova/`, `directory/`, `identity/` e `jellyfin/config/`. Guardar também o YAML de instalação correspondente; caso tenhas atualizado a imagem, os três serviços NOVA nesse ficheiro devem apontar para o mesmo digest atual.
3. Criar uma chave age **fora dessa pasta de estado**, ou reutilizar a chave de recuperação guardada:

```powershell
age-keygen -o ..\CHAVE_PRIVADA_RECUPERACAO.key
$novaRecipient = age-keygen -y ..\CHAVE_PRIVADA_RECUPERACAO.key
python server/scripts/recovery.py backup --state ..\COPIA_OFFLINE --output ..\NOVA_BACKUP.age --recipient $novaRecipient --deployment ..\instalar-no-truenas.yaml --services-stopped
```

A cópia de estado no PC contém segredos e deve ficar em local privado até ser removida pelo proprietário. O arquivo final é cifrado; não é uma cópia dos ficheiros de media. O comando recusa sobrescrever um arquivo existente.

## Restauro para um novo dataset

Usar a ferramenta e o `IMAGE.txt` desta entrega. O restauro exige uma imagem explícita para evitar arrancar automaticamente um runtime antigo que ignore a revogação de provas anteriores ao restauro.

```powershell
python server/scripts/recovery.py restore --input ..\NOVA_BACKUP.age --output ..\RESTAURO_NOVO --identity ..\CHAVE_PRIVADA_RECUPERACAO.key --lan-state-root /mnt/POOL/nova-restaurado --image-file ..\servidor\IMAGE.txt
```

O comando cria apenas uma pasta local nova e devolve `ABRIR_RESTAURO.md`, `RECUPERACAO.json`, `NOVA-LAN-CA.crt`, `instalar-no-truenas.yaml`, `deployment.original.txt` e `state/`. Copiar o conteúdo de `state/` para o dataset novo, confirmar UID/GID e ACL privados e instalar o YAML novo nas Apps. O YAML é regenerado pelo perfil restrito; o deployment original é apenas um registo, nunca é executado. O IP privado e as origens de media mantêm-se. Não iniciar duas instalações com a mesma identidade/IP.

Uma chave age errada ou um arquivo alterado/truncado não publica um diretório restaurado. Não se sobrepõe a uma instalação existente. Certificados expirados são preservados para recuperar a identidade e assinalados no relatório; o runtime continua a recusá-los até uma rotação autorizada.

## Recuperar acesso

- Identidades NOVA/Directory e TLS mantidas: a configuração de confiança existente na TV deve continuar válida.
- Sessões NOVA, Jellyfin e Directory, pedidos de associação, dispositivos, permissões/credenciais de media e agentes de renovação invalidados.
- Registos Directory deixam de ser descobertos até o proprietário entrar e publicar novamente. Provas de associação emitidas antes do restauro são recusadas mesmo dentro do prazo original.
- As contas, partilhas e estados de desativação **da data da cópia** são recuperados como configuração. Rever antes de republicar: o snapshot não contém revogações feitas depois dele. Uma partilha de descoberta não restaura permissão de media.
- No Control, entrar novamente, verificar Jellyfin/indexação, publicar com a conta proprietária e voltar a atribuir bibliotecas/aprovar cada TV. Não é necessário recriar o servidor nem configurar outro fingerprint.

## Prova exigida

Os testes locais exercitam arquivos maliciosos, identidade em falta/trocada, chave de credenciais, YAML inseguro e a barreira temporal das provas. O ensaio Docker faz backup cifrado, rejeita adulteração/truncagem/chave errada, arranca os quatro serviços restaurados num dataset novo, verifica identidades, recusa credenciais antigas e volta a obter catálogo/vídeo depois de nova autorização. A imagem exata é ensaiada antes de publicar.

Resultados finais desta revisão por registar. A aceitação física TrueNAS/Xiaomi/Chromecast, assinatura de produção e SEC-01…12 mantêm os seus gates; WireGuard, Tailscale e NetBird nativos completos continuam M5.
