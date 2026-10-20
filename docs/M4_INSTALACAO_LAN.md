# M4 — Instalação LAN guiada

Implementação em validação. Este documento acompanha o novo perfil LAN; a [prova anterior do catálogo/player](M4_CINEMA_LOCAL.md) continua preservada.

## Percurso preparado

O proprietário executa um assistente no PC: IP privado reservado do NAS, versão TrueNAS, três datasets sem sobreposição, UID/GID de serviço e conta inicial. O assistente cria uma pasta NOVA nova, com estado proprietário/Directory, certificados por serviço e YAML completo para as Apps. Não acede ao NAS nem substitui instalações existentes.

```powershell
python -m pip install --require-hashes -r server/requirements-directory.txt
python server/scripts/lan_install.py --output NOVA_LAN_NOVA --image-file IMAGE.txt
```

Usar o `IMAGE.txt` da entrega LAN que contém este runtime. Uma imagem 0.7 anterior não contém `nova_server.lan_launch`. O instalador usa `getpass`; palavras-passe não são argumentos nem ficam em texto simples nos ficheiros. A conta inicial NOVA e a conta proprietária Directory têm a palavra-passe inicial escolhida, com hashes independentes. A conta administrativa Jellyfin é configurada no Control.

O resultado inclui:

- `ABRIR_PRIMEIRO.md`: instruções específicas aos valores escolhidos.
- `instalar-no-truenas.yaml`: Compose completo, imagem por digest, três endpoints HTTPS presos ao IP privado escolhido.
- `copiar-para-nas/`: conteúdo inicial a transferir para o dataset de estado NOVO.
- `NOVA-LAN-CA.crt`: CA pública a importar no navegador/PC do proprietário antes de abrir Control.
- `GUARDAR-OFFLINE-ca.key`: chave privada da CA; não copiar para o NAS/TV nem para uma partilha pública.
- `INSTALACAO.json`: endereços, fingerprint público e UID/GID, sem palavras-passe.

Preparar no TrueNAS os datasets/ACL e transferir o conteúdo inicial por um método administrativo suportado, preservando propriedade UID/GID e permissões privadas. O diretório de destino tem de ser novo e vazio. A cópia não é automatizada e não exige SSH ao gerador. Em Windows, confirmar permissões depois da transferência: o ACL do PC não substitui o ACL/POSIX no NAS. O runtime recusa estado ausente ou chave TLS com permissões públicas em POSIX.

O proprietário instala o YAML nas Apps, abre Control por HTTPS, configura Jellyfin/bibliotecas e publica no Directory. O painel apresenta endereço e fingerprint para preparar a TV; permite criar uma conta de familiar e permitir descoberta. Essa criação não autoriza media: a TV apresenta código, o proprietário atribui bibliotecas e aprova.

## Separação de serviços

| Serviço | Publicação no perfil LAN | Estado/chaves disponíveis |
|---|---|---|
| Control | HTTPS no IP privado, porta 9444 por defeito | Estado NOVA, chave TLS administrativa e certificados públicos Directory/media |
| Cliente/media | HTTPS no IP privado, porta 8920 | Estado NOVA e chave TLS de cliente; sem rotas Control/Directory |
| Directory | HTTPS no IP privado, porta 9443 | Estado Directory e respetiva chave TLS; sem estado NOVA/Jellyfin |
| Jellyfin | Sem porta publicada | Config/cache e duas origens só de leitura |

Os launchers M2/M3 e o YAML antigo conservam o comportamento de laboratório anterior. A publicação LAN é explícita através deste novo gerador. Não usa `privileged`, rede host ou socket Docker. As três chaves TLS são distintas; a chave de assinatura CA fica offline.

## Configuração nativa da TV

A APK 0.8-m4-lan-lab permite **Entrar na NOVA → Configurar nesta TV**. O proprietário introduz o Directory privado e os 64 caracteres do fingerprint TLS mostrados no Control/pacote. A app valida o certificado exato, prazo, hostname e TLS 1.3, obtém apenas o bootstrap público e autentica a configuração persistida com Keystore/AES-GCM.

Não aceita HTTP, redirects, fingerprint diferente ou um bootstrap cujo certificado não seja o do canal validado. Uma identidade já aprovada não é substituída silenciosamente; configuração cifrada danificada bloqueia a entrada. Não é necessário ADB para transferir o perfil nem `adb reverse` para a ligação LAN. Depois deste passo do proprietário, o familiar usa a própria conta.

## Validação e limites

Os gates novos ensaiam o YAML gerado com Jellyfin Docker real, configuração/publicação a partir dos contentores, criação de familiar, associação, catálogo/Range e persistência após reinício. A prova Android ensaia setup com D-pad, pin incorreto, HTTP, configuração persistida, login/aprovação e primeiro frame pelo IP privado do runner, sem `adb reverse`. O ADB é apenas o mecanismo de instalação/instrumentação dos emuladores CI.

Ainda falta registar aqui o resultado final dos gates desta revisão. Aceitação física no TrueNAS Community, Xiaomi Box S2 e Chromecast continua pendente. Modelo/geração do Chromecast e versão concreta do TrueNAS continuam por recolher no ensaio físico. Não prometer compatibilidade 4K/HDR/áudio por estes testes sintéticos.

Este gerador é para instalação NOVA; não migra estado M2/M3/M4 existente nem altera IP/identidade de uma instalação ativa. O backup/restauro M2 anterior não abrange toda esta nova pasta Directory/TLS. Guardar o pacote inicial de forma privada não equivale a um backup atualizado. Recuperação integrada, assinatura definitiva da APK e segurança final mantêm os gates próprios. Certificados de serviço têm validade inicial de um ano; rotação e recuperação exigem preservar as identidades existentes. WireGuard, Tailscale e NetBird completos continuam na M5; SEC-01…12 sem aceitação final.

## TrueNAS

[Instalação de Custom Apps](https://apps.truenas.com/managing-apps/installing-custom-apps/) descreve a preparação prévia dos datasets e a opção Install via YAML. O gerador aceita a base Docker Apps 24.10+ e exige a versão concreta fornecida pelo proprietário; a aprovação Docker não certifica a versão instalada no NAS.

Para o dataset de estado **novo**, preferir preset Generic/POSIX. O [editor de permissões TrueNAS 25.10](https://www.truenas.com/docs/scale/25.10/scaleuireference/datasets/editaclscreens/) permite escolher proprietário/grupo, confirmar Apply User/Group e aplicar permissões aos ficheiros/diretórios. Após a transferência, atribuir UID/GID ao serviço e limitar o acesso ao proprietário, preservando execução/travessia dos diretórios. Uma aplicação recursiva deve limitar-se ao dataset NOVO de estado; não alterar recursivamente as origens de media existentes. As chaves criadas no PC têm modo 600 e os diretórios privados 700 em POSIX. A confirmação destes modos/ACL no NAS faz parte da aceitação física.
