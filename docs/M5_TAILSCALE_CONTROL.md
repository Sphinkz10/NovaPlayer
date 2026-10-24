# Tailscale no Control — aprovação do perfil e preparação TLS

Incremento em validação. O proprietário já pode comparar e aprovar/desativar um
perfil Tailscale preparado, ligado ao servidor e ao certificado. Não equivale à
inscrição do peer no tailnet nem à instalação automática do gateway.

## Preparação antes da primeira TV

O IP overlay só é conhecido depois de inscrever o peer Tailscale. O certificado
NOVA precisa de incluir esse IP, mantendo a CA e a chave privada existentes.
`server/scripts/tailscale_prepare.py` usa a CA offline da instalação LAN original
e produz uma pasta nova de atualização, sem alterar o original ou prolongar a
validade do certificado. Recusa dispositivos já associados, publicação Directory
anterior, outro perfil remoto, saída dentro do original e ficheiros inconsistentes.

O comando exige a imagem NOVA Core desta revisão, fixada por digest. Uma imagem
0.12 anterior não implementa este contrato. A APK distribuída permanece a 0.12
LAN/WireGuard; o motor Tailscale ainda usa a variante de laboratório.

```powershell
python server/scripts/tailscale_prepare.py --installation C:\NOVA_LAN_ORIGINAL --output C:\NOVA_TAILSCALE_PREPARADO --gateway 100.64.0.1 --image ghcr.io/sphinkz10/nova-core@sha256:DIGEST_DA_IMAGEM_TESTADA
```

O IP é um exemplo: tem de ser o do peer dedicado ao NOVA Server. O preparador
não instala esse peer, não cria uma rede no NAS e não acrescenta portas ou
privilégios ao Compose. Ler o guia produzido antes de aplicar os quatro ficheiros
públicos e reiniciar os serviços. A chave privada da CA fica no PC/offline.

## Aprovação e desativação

No Control, o proprietário compara coordenador, origens LAN/Tailscale e SHA-256 do
certificado. A decisão exige revisão e digest da política completos; uma página
antiga não pode aprovar outra configuração ou outro certificado. Nenhuma chave
de inscrição, URL nova ou opção de rede é aceite por este endpoint.

Em modo gerido, o servidor recusa emitir perfis e receber pedidos pelo endereço
Tailscale até à aprovação. Desativar bloqueia novos pedidos e interrompe a leitura
de vídeo já iniciada, sem revogar a associação LAN. Não remove o peer do tailnet.
O estado mantém `gateway_verified=false` e `remote_access_enabled=false`.

A recuperação conserva a identidade, os certificados e a política, mas invalida
a aprovação e exige nova decisão do proprietário. O estado do daemon Tailscale
não faz parte deste perfil/cópia. O instalador do gateway, inscrição pelo Control,
SaaS, distribuição Android, ciclo de vida/renovação e NetBird continuam pendentes.

## Validação em curso

O teste de navegador real cobre a revisão, aprovação, reload, desativação, logout
durante resposta pendente e ausência de credenciais no armazenamento do browser.
Os testes Python cobrem confiança, concorrência, restauro, isolamento de papéis e
corte de stream em curso. O ensaio Android repete catálogo/player pelo motor real
e verifica a desativação/reaprovação no Control sem desligar o túnel Tailscale.
Os resultados finais serão registados após concluir os jobs API 26/35 e Docker.
