# Tailscale no Cinema — integração em validação

O incremento liga a prova de transporte nativo ao mesmo catálogo, capas e player
usados na versão 0.12. Ainda não altera o APK distribuído: a variante normal
continua sem carregar o motor Tailscale, e a versão 0.12 mantém-se a instalação
de teste para LAN/WireGuard.

## Contrato implementado

- `GET /api/v1/device/tailscale/profile` exige a credencial ativa da própria TV.
  Associação revogada, conta desativada e credencial administrativa não dão acesso.
- O serviço só ativa o contrato quando recebe uma política pública explícita por
  `NOVA_TAILSCALE_PUBLIC_CONFIG`, em ficheiro privado, com identidade do servidor,
  revisão, origem HTTPS do coordenador e origem HTTPS num único IPv4 `100.64/10`.
- O perfil tem validade máxima de 24 horas, fica ligado ao servidor, dispositivo,
  conta e origem LAN existentes. Não contém auth key, certificado novo, DNS,
  rotas de sub-rede ou exit node. Aprovação NOVA e admissão no tailnet continuam
  decisões independentes.
- A TV mantém o certificado já aprovado e valida hostname, pin e TLS 1.3 nas
  ligações de identidade, catálogo, capas e vídeo. O transporte fica em memória;
  os tokens renovados são guardados sob a identidade LAN original no Keystore.
- A seleção Tailscale persiste: após perda do processo/túnel, as operações recusam
  acesso até reconexão explícita. Não existe fallback automático para LAN.
  WireGuard recusa preparação/ativação enquanto Tailscale estiver selecionado.

## Validação

38 testes novos do servidor aprovados localmente. A bateria JVM passou 225
verificações e a política nativa Tailscale passou 42. O APK de laboratório e a
instrumentação compilaram com o AAR nativo identificado no documento anterior.

A execução nas APIs 26/35 está a ser preparada para testar: perfil recebido por
HTTPS LAN, seleção do transporte, catálogo com biblioteca autorizada, recusa de
outra biblioteca, capas, detalhe, frame Media3 real, avanço, pausa, regresso do
background, retoma e progresso guardado. Reutiliza o percurso funcional M4, com
vídeo e upstream Jellyfin sintéticos dentro do namespace privado.

Os resultados dos emuladores só serão registados como aprovados após a execução.
O coordenador do laboratório é Headscale; não é uma conta Tailscale SaaS.

## Para disponibilizar a opção ao utilizador

Faltam a configuração/admissão pelo Control, instalação do peer no servidor,
gestão segura da autorização inicial sem ficheiros de ensaio, coordenador SaaS,
renovação/expiração do perfil e distribuição do adaptador nativo após validação.
NetBird, hardware físico, rede externa e SEC 0/12 permanecem pendentes.
