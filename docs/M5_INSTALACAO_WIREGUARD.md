# NOVA 0.10 — instalação de teste com WireGuard nativo

Esta entrega acrescenta o gateway Docker e o percurso WireGuard na NOVA Cinema. Destina-se a uma instalação nova de teste. Não existe ainda validação física no teu TrueNAS, Xiaomi Box S2 ou Chromecast.

## Preparar o servidor no PC

1. Extrai `NOVA_M5_GATEWAY_fontes.zip` nesta pasta. Abre PowerShell na pasta extraída `NOVA_Fase1`.
2. Usa Python 3.12/3.13 e executa:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r server/requirements-directory.txt
$novaCore = (Get-Content ..\servidor\IMAGE.txt).Trim()
$novaGateway = (Get-Content ..\gateway\IMAGE.txt).Trim()
.\.venv\Scripts\python.exe server/scripts/wireguard_install.py --output ..\NOVA_WIREGUARD_TESTE --image $novaCore --gateway-image $novaGateway
```

O assistente pede o IP privado reservado do NAS, versão TrueNAS, dataset de estado novo, duas origens de media, UID/GID da conta de serviço, proprietário e palavra-passe. Pede também o endpoint UDP, a rede WireGuard e o IP do gateway. Exemplo de rede: `10.222.0.0/24`, gateway `10.222.0.1`; escolher uma rede que não se sobreponha às redes de casa ou de onde ligará a TV. Para um primeiro ensaio local, o endpoint pode ser `IP_PRIVADO_DO_NAS:51820`.

O PC não precisa de Docker nem de SSH para gerar os ficheiros. A imagem fornecida exige CPU x86-64 e uma versão TrueNAS Community com Apps Docker. Não instalar pacotes no sistema base do NAS. O kernel tem de suportar WireGuard e nftables.

3. Segue **ambos** os ficheiros gerados: `NOVA_WIREGUARD_TESTE/ABRIR_PRIMEIRO.md` e `WIREGUARD.md`. Transfere o estado privado para o dataset indicado, aplica os UID/GID e permissões descritos e instala o YAML nas Apps. O pacote gerado contém chaves privadas; conserva-o em privado. As duas origens de media são montadas só para leitura.
4. Abre NOVA Control, termina a configuração Jellyfin/Directory, atribui bibliotecas e cria a conta familiar. Mantém administração, Directory e Jellyfin acessíveis apenas na rede privada. O gateway publica UDP 51820 no IP reservado do NAS.

## Instalar e ligar a TV

1. Instala `NOVA-Cinema-0.10-M5-WireGuard.apk` na Xiaomi Box S2, Chromecast ou Android TV/Google TV API 26+. É a mesma identidade da 0.9, com versionCode superior; uma atualização normal conserva os dados. Não é necessário desinstalar a versão anterior.
2. Na LAN, configura o Directory e confirma a impressão digital; entra com a conta familiar, associa a TV e aprova-a no Control.
3. Abre o Cinema e confirma catálogo/vídeo pela LAN.
4. No ecrã inicial, seleciona **Preparar WireGuard nesta TV**. Compara a impressão digital no Control e aprova a inscrição WireGuard. Seleciona **Preparar** novamente para receber o perfil público. A chave privada fica na TV.
5. Seleciona **Ligar WireGuard**, aceita o pedido VPN do Android e espera pela confirmação da identidade do servidor. Abre o Cinema e testa vídeo, avanço, pausa e retoma.
6. Para regressar à LAN, seleciona explicitamente **Desligar WireGuard e usar LAN**. Uma falha ou reinício da app com WireGuard selecionado bloqueia o acesso até voltares a ligar ou escolheres LAN.

Para um ensaio fora de casa, o endpoint configurado tem de ser alcançável pela TV. O proprietário configura o encaminhamento **apenas UDP WireGuard** no router. Esta versão não ultrapassa CGNAT automaticamente. O perfil expira após 24 horas e a renovação ainda exige regressar à LAN e preparar novamente.

## Critérios do teu ensaio

- Cinco serviços saudáveis; duas origens reconhecidas; biblioteca de cada familiar limitada ao que foi atribuído.
- Instalação/atualização, comando, reprodução, avanço e retoma em cada box.
- WireGuard confirmado; vídeo pelo túnel; revogação no Control impede novo acesso remoto.
- Reinício do conjunto Compose conserva identidade e configuração. Atualizar/reiniciar gateway e cliente em conjunto, pois partilham o namespace de rede.

Os resultados automáticos e hashes estão em `M5_GATEWAY_RESULTADOS.json` e `SHA256SUMS.txt`. As capturas em `prints/index.html` são reais de emuladores, com vídeo sintético; não demonstram codecs/HDR nem desempenho dos aparelhos físicos.

## O que ainda falta

M3 está concluída no software; M4 LAN está disponível para aceitação física. Este pacote conclui o incremento WireGuard Docker/TV em laboratório, sujeito aos resultados incluídos. **M5 completa continua aberta:** Tailscale e NetBird nativos, descoberta/renovação remota, recuperação cifrada do perfil de cinco serviços e aceitação em rede externa/aparelhos físicos.

Não usar o recuperador M4 LAN no perfil novo de cinco serviços: essa integração ainda falta. Não atualizar uma instalação ativa com este gerador; ele prepara destinos novos. Guarda as entregas anteriores e o seu estado de forma independente. Validações finais de segurança SEC-01…12: **0/12**. Esta não é ainda a versão para utilização familiar em produção.
