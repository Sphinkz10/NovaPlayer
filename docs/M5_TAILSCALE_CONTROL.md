# Tailscale no Control — aprovação do perfil e preparação TLS

Estado em 24 outubro 2026: **aprovação/desativação do perfil validada em laboratório**. O proprietário já pode comparar e aprovar/desativar um
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
python server/scripts/tailscale_prepare.py --installation C:\NOVA_LAN_ORIGINAL --output C:\NOVA_TAILSCALE_PREPARADO --gateway 100.64.0.1 --image ghcr.io/sphinkz10/nova-core@sha256:8e116b88e8558f1d9b0fa66cee2ed7dfa15104d003042d7bf7e07f61b77036bb
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

## Validação concluída neste incremento

O teste de navegador real cobre a revisão, aprovação, reload, desativação, logout
durante resposta pendente e ausência de credenciais no armazenamento do browser.
Os testes Python cobrem confiança, concorrência, restauro, isolamento de papéis e
corte de stream em curso. O ensaio Android repete catálogo/player pelo motor real
e verifica a desativação/reaprovação no Control sem desligar o túnel Tailscale.
**17/17 jobs aprovados**, incluindo Docker e regressão LAN/WireGuard. Tailscale: **39 verificações Android + oito do laboratório em cada API 26/35**; inclui recusa de Host LAN falsificado no socket overlay. Control: nove verificações em navegador real. Python por versão 3.12/3.13: Linux 471 aprovados + uma exclusão; Windows 463 + nove. [Revisões, resultados e tentativas](M5_TAILSCALE_CONTROL_RESULTADOS.json).

A identificação do caminho remoto usa também o destino real do socket e a origem CGNAT; o cabeçalho Host não é uma autorização. A recuperação integral do perfil e a interrupção de streams têm testes próprios. O ensaio de rede usa Headscale e upstream Jellyfin sintéticos; não certifica SaaS nem aparelhos físicos.

O AAR nativo foi preservado sem reconstrução: SHA-256 `224bfc4ef95c9c173f1a2d62a377f129333313c1cb622b4d229cf37b6403e0a0`, artefacto `12568188539`, execução `40116217702`, retenção até 23 novembro 2026. JNI API 26/35 novamente aprovado na execução `40116439071`. A preservação é temporária e exige uma nova retenção antes de expirar.
