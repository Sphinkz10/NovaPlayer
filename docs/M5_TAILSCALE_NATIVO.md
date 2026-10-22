# M5 — Tailscale nativo: serviço VPN e ensaio de rede

Estado em 22 outubro 2026: **prova de transporte nativo aprovada nas APIs 26 e 35**,
na [execução 39800485304](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39800485304),
fonte `66d78529e10550e985614a78e22e10cc50b34f33`. Cada API passou 29 verificações
Android e sete verificações do harness; a política passou 42 casos JVM.
A perda da chave Keystore foi recusada antes do arranque, sem regeneração da
identidade. [Resultados e proveniência](M5_TAILSCALE_RESULTADOS.json).
A entrega instalável continua a ser a 0.11 WireGuard. A M5 completa permanece aberta.

O adaptador em `connect/tailscale-native` usa o motor real `libtailscale`, já
compilado a partir do commit Android `264102cc702fbd844e900227ee02e5cbb4d7f801`.
O AAR combinado tem SHA-256
`224bfc4ef95c9c173f1a2d62a377f129333313c1cb622b4d229cf37b6403e0a0`.
Continua num processo privado `:nova_overlay`, separado do JNI WireGuard.

O novo serviço exige consentimento VPN, executa em primeiro plano, aceita apenas
comandos internos do mesmo UID e não expõe uma API LocalAPI arbitrária.
O armazenamento sela cada entrada com AES-GCM e Android Keystore; a verificação
anterior ao arranque impede a substituição silenciosa de identidade quando há
dados alterados ou falta a chave. A identidade fica associada ao coordenador e
ao endereço do gateway. As rotas pedidas pelo motor são reduzidas ao gateway
aprovado `/32`, apenas para a app NOVA; sem rotas LAN/default/exit node, anúncios
de sub-redes ou captura de DNS. A validação CGNAT é específica deste adaptador;
as regras LAN e WireGuard existentes permanecem separadas.

O workflow `tailscale-network.yml` verifica API 26/35 com:

- consentimento pelo diálogo real do Android;
- inscrição com chave de uso único, válida por dez minutos;
- serviço NOVA Core HTTPS numa namespace Linux, acessível pelo túnel real;
- TLS 1.3, certificado exato e verificação de hostname da plataforma;
- recusa de certificado diferente e das portas SSH/administração com serviços vivos;
- reconexão com a mesma identidade após force-stop, sem reutilizar a chave de inscrição;
- recriação do serviço no mesmo processo, reutilizando uma única Application Go;
- corte de acesso após expirar o nó no coordenador e ao desligar localmente;
- recusa de estado cifrado adulterado ou perda da chave Keystore antes de inicializar o motor.

A primeira execução, `39798188270` / fonte `625a097`, falhou na inicialização nas
duas APIs e não conta como aprovada. A correção trata a resposta vazia da LocalAPI
como sucesso sem corpo: gomobile pode devolvê-la como `null`. Foi também corrigida
a duração do motor, que agora existe uma única vez por processo, e o sentinela
de política não configurada foi alinhado com a API upstream. O novo ensaio inclui
diagnóstico por etapa/classe de erro, sem mensagens do coordenador ou credenciais.

Neste PC a compilação Kotlin e os 42 casos JVM usaram as classes reais do AAR
verificado, num AAR reduzido apenas para compilação, sem bibliotecas JNI, devido
ao espaço livre. A execução GitHub usa o AAR completo, verifica o SHA-256 antes
do build e executa o túnel real. O teste NOVA local confirmou `/device/me` autenticado
numa origem CGNAT, recusa sem credencial e ausência das rotas administrativas.

O coordenador descartável é Headscale 0.29.5; o par Linux usa Tailscale 1.104.2.
Os dois binários são fixados por SHA-256 em `network.py`. A namespace não encaminha
tráfego e o host não recebe uma rota para o endereço overlay. Não há proxy TCP,
ADB reverse nem app VPN externa. As credenciais temporárias e os estados privados
ficam fora dos artefactos publicados; os logs exportados são limitados e expurgados.
O AAR anterior é verificado antes da compilação. O APK de ensaio não substitui o
APK de distribuição nem ativa Tailscale no menu normal.

Ainda faltam a inscrição/configuração pelo NOVA Control, o instalador do gateway
Tailscale no servidor, autenticação numa conta Tailscale SaaS, troca segura entre
fornecedores e reprodução Media3 por este transporte. Este ensaio não certifica
TrueNAS nem boxes físicas e não equivale às 12 validações finais de segurança.

Referências primárias para a configuração do laboratório:
[configuração Headscale 0.29.5](https://github.com/juanfont/headscale/blob/v0.29.5/config-example.yaml),
[chaves de inscrição Headscale](https://github.com/juanfont/headscale/blob/v0.29.5/cmd/headscale/cli/preauthkeys.go),
[Android VPN](https://developer.android.com/develop/connectivity/vpn).
