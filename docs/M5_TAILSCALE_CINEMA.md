# Tailscale no Cinema — percurso funcional aprovado em laboratório

Estado em 24 outubro 2026: **catálogo, capas e player Media3 pelo Tailscale nativo
aprovados nas APIs 26 e 35**, fonte `6e9550c9e9b49e4bfca10589a87194ed385d6ad9`.
Cada API passou **36 verificações Android e sete do laboratório**. A política
nativa passou 42 casos JVM. [Prova de rede/reprodução](https://github.com/Sphinkz10/NovaPlayer/actions/runs/40036059678).
[Resultados, jobs, tentativas e hashes](M5_TAILSCALE_CINEMA_RESULTADOS.json).

O incremento liga o motor à mesma app e aos mesmos clientes de identidade,
permissões, catálogo, capas e reprodução usados na 0.12. O arranque/admissão
continua conduzido pela instrumentação e por uma autorização Headscale descartável.
A APK distribuída continua a ser **NOVA Cinema 0.12 LAN/WireGuard**, preservada.
Ainda faltam o Control, instalador e distribuição da opção Tailscale normal.

## Perfil autorizado e identidade

- `GET /api/v1/device/tailscale/profile` exige a credencial ativa da própria TV.
  Revogação, conta desativada e credencial administrativa não dão acesso.
- O serviço só ativa o contrato quando recebe uma política pública explícita por
  `NOVA_TAILSCALE_PUBLIC_CONFIG`, em ficheiro privado, com identidade do servidor,
  revisão, origem HTTPS do coordenador e origem HTTPS num único IPv4 `100.64/10`.
- O perfil tem validade máxima de 24 horas, ligado ao servidor, dispositivo,
  conta e origem LAN existentes. Não contém auth key, certificado novo, DNS,
  rotas de sub-rede ou exit node. Aprovação NOVA e admissão no tailnet são
  decisões independentes; este contrato não concede a segunda.
- A TV conserva o certificado já aprovado e valida hostname, pin e TLS 1.3.
  Os tokens renovados são guardados sob a identidade LAN original no Keystore.
- A seleção Tailscale persiste. Sem processo/túnel válido, as operações recusam
  acesso até reconexão explícita. WireGuard recusa preparação/ativação enquanto
  Tailscale está selecionado; a queda do túnel não escolhe LAN automaticamente.

## Percurso executado

O ensaio recebe o perfil por HTTPS LAN autenticado, liga o motor nativo num
processo privado separado do JNI WireGuard e seleciona o transporte para a sessão
NOVA. Exercita o início, biblioteca autorizada, recusa de outra biblioteca,
pesquisa, capas, detalhe, preservação do foco, frame Media3 real, avanço, pausa,
regresso do background ainda pausado, progresso guardado e retoma. As dez capturas
incluídas na entrega são imagens reais destes ecrãs, com dados/vídeo sintéticos.

O servidor NOVA e o upstream Jellyfin sintético ficam numa namespace Linux sem
encaminhamento. O host não tem rota para o gateway e não há proxy TCP, ADB reverse
ou app VPN externa. Há serviços vivos nas portas SSH/administração, recusados
pelo túnel. A prova repete reconexão com a mesma identidade após force-stop e
recriação do serviço; expirar o nó no coordenador corta HTTPS e acesso ao catálogo
enquanto a credencial NOVA continua válida. Estado adulterado ou chave Keystore
ausente continuam recusados antes de inicializar o motor.

O coordenador é **Headscale de laboratório**, não uma conta Tailscale SaaS. A
prova usa o AAR combinado SHA-256
`224bfc4ef95c9c173f1a2d62a377f129333313c1cb622b4d229cf37b6403e0a0`,
o mesmo motor e isolamento documentados na [prova de transporte anterior](M5_TAILSCALE_NATIVO.md).

## Regressão e limites

**17/17 jobs aprovados na mesma revisão de código**, reunindo os jobs originais
que passaram e os dois relançamentos de preparação. Inclui Python 3.12/3.13 em
Linux (440 + 1 exclusão por versão) e Windows (432 + 9), 225 verificações JVM,
build/lint, Docker real, recuperação, distribuição/atualização e percursos
LAN/WireGuard API 26/35, além dos dois Tailscale. Lint release local: zero erros,
44 avisos, sem supressão nova.

O Tailscale executou o commit de origem `6e9550c`; os ensaios do PR usam o merge
temporário de CI `f15309ad587e15b3a3c0dd74aa4d0276803cb661`. A árvore Git completa
foi comparada e é idêntica entre ambos. Este merge de ensaio não integra o PR.

Duas tentativas foram canceladas durante downloads lentos de dependências FFmpeg
do mirror Ubuntu, antes dos testes Android: Tailscale 26 e associação 35. Apenas
esses jobs foram relançados, sem alterar o código ou os critérios de aprovação.
O relatório conserva os ids e o motivo; não contabiliza cancelamentos como passes.

Para disponibilizar Tailscale normalmente faltam configuração/admissão pelo
Control, instalação do peer no servidor, gestão da autorização inicial fora da
instrumentação, SaaS, expiração/renovação do perfil e ciclo de vida/troca de
fornecedor. NetBird completo, reconexão após expiração offline, rede externa,
TrueNAS/Xiaomi/Chromecast físicos e SEC 0/12 permanecem pendentes. **M5 aberta.**
