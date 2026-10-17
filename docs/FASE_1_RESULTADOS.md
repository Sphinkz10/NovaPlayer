# NOVA — Resultados da primeira fase

17-10-2026 · Server 0.1.1 · Connect laboratório 0.4-phase1

A base foi corrigida e testada localmente e no GitHub. O arranque conjunto em
Docker Linux já passou. A instalação no TrueNAS, o player e a ligação real
pelos três motores continuam por demonstrar.

## Alterações implementadas

- Login Control corrigido: conserva a referência ao formulário durante pedidos
  assíncronos, limpa a palavra-passe e mantém a sessão apenas em memória.
- Reserva atómica de tentativas em SQLite antes de Argon2: cinco tentativas
  falhadas/em curso por origem em 15 minutos. Sucesso só remove a sua reserva;
  máximo de duas verificações Argon2 simultâneas por processo.
- Conexões SQLite fechadas explicitamente. Host administrativo limitado a
  localhost/127.0.0.1. Dependências Python fixadas com hashes transitivos.
- Diagnóstico Jellyfin limitado a 16 KiB e quatro segundos totais; recusa
  redirecionamentos, compressão e tipos inválidos. Valida produto, ID, wizard
  e, quando configurada, identidade esperada.
- Corrigido um erro revelado pela integração real: o produto oficial é
  **Jellyfin Server**, não o valor usado pelos mocks anteriores. Python e
  Android agora usam esse valor, com regressões para a resposta incorreta.
- Overview distingue origens configuradas de leitura, indexação e proteção
  contra escrita efetivamente observadas.
- NOVA Control guarda rascunhos autenticados WireGuard, Tailscale e NetBird;
  valida campos por fornecedor, rejeita segredos/campos desconhecidos,
  persiste em SQLite e regista eventos sem valores. Ainda não inscreve peers.
- Android deteta SDK/ABI/Leanback, sem lista de marcas. Contratos distinguem
  motor ausente, incompatibilidade, consentimento, túnel, serviço e revogação.
  Não existe mudança silenciosa de fornecedor.
- Política de reprodução distingue remux, áudio, vídeo e legendas. Manifest TV
  inclui banner/ícone e exclusões de cópia/transferência de dados.
- Gradle Wrapper 8.11.1, locks e verificação SHA256 dos artefactos Maven;
  os checksums normais não são regenerados durante a CI.
- Prova experimental de compilação conjunta Tailscale/NetBird num único AAR
  para evitar classes/runtime gomobile duplicados. Não ativa motores na app.

## Evidência remota

Código testado: `bf0702583978e61254418fe3d8d94c1cbdff3533`.
[Execução de integração](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39069361596).
A revisão `5a7f71ab62522e0179220b32d651339268d3f4b5` repetiu com sucesso
os sete jobs na [CI atualizada](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39074987869).

| Verificação | Resultado observado |
|---|---|
| Python Linux 3.12 e 3.13 | **93 aprovados** em cada versão |
| HTTP NOVA Core | Bootstrap, login, overview e Jellyfin desligado aprovados |
| Chromium Linux real | Dez verificações aprovadas, incluindo três rascunhos persistidos e zero erros JS |
| Kotlin num runner Linux limpo | **166 aprovados**: 117 políticas, 19 HTTP simulado, 30 fornecedor/compatibilidade |
| Android | APK debug e lint aprovados, sem regenerar checksums |
| Dependências Python runtime | Nenhuma vulnerabilidade conhecida encontrada pelo pip-audit |
| Docker Compose real | **Aprovado**: Core + Jellyfin, duas origens legíveis com escrita bloqueada |
| Reinício Docker | Proprietário e sessão persistiram; token bootstrap removido |
| Windows 3.12/3.13 | **89 aprovados, 4 ignorados** por versão; HTTP e Chromium aprovados |
| Motores nativos | AAR Tailscale/NetBird e APK com WireGuard compilados |
| Runtime Android API 26/35 | **4/4 combinações aprovadas**, com processos privados separados, em x86_64 |

A prova Docker usa um projeto único e diretórios temporários com ficheiros
sintéticos. Verifica HTTP, diagnóstico do Jellyfin, bootstrap/login, leitura,
escrita bloqueada e persistência após restart. Não indexa filmes nem demonstra
compatibilidade TrueNAS ou reprodução. Em falha preserva diagnóstico nos logs
antes de remover apenas o projeto temporário.

O primeiro ensaio JNI detetou SIGSEGV em API 35 ao carregar gomobile antes de
WireGuard no mesmo processo. O teste corrigido usa um serviço privado para
Tailscale/NetBird e exige PIDs distintos. Ambas as ordens passaram nos dois
emuladores: [evidência](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39074985057).
O serviço é uma prova debug de carregamento, sem inscrição nem túnel. Processos
privados continuam dentro da mesma APK e usam o mesmo UID Android.

## Evidência local e artefactos anteriores

O primeiro snapshot local passou 88 testes Python, com quatro exclusivos de
Linux ignorados em Windows; HTTP real, Edge e 165 testes Kotlin também passaram.
APK debug assinada v2, quatro ABIs WireGuard e alinhamento ZIP de 16 KiB
verificados. Lint: zero erros e dez avisos. Alinhamento não prova execução
num dispositivo com páginas de 16 KiB.

A APK local `NOVA_Connect_Lab_v0.4-phase1-debug.apk` tem SHA256
`1751db3d5a979f6920e012cb5b1b9b2c3c09e909847a1c56e6e0698fc87ee348`.
Esse snapshot antecede a correção de produto Jellyfin. Usar os artefactos da
execução remota identificada acima para a revisão mais recente; não confundir
a assinatura debug do runner com uma chave de distribuição definitiva.
Os ZIPs históricos em archives não recebem estas correções.

## Limites e sequência seguinte

M1 já tem provas Linux, navegador, Android e Docker. A compilação conjunta de
Tailscale/NetBird e a APK com os três motores passaram na
[prova nativa](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39069358627).
M0 permanece aberto: Tailscale e NetBird precisam de ponte Android funcional,
consentimento, persistência, inscrição por dispositivo e HTTPS real.
Ver [ensaio nativo](../connect/native-proof/README.md) e
[ADR 001](ADR_001_CONNECT_NATIVO.md).

Ainda não houve instalação no TrueNAS/Xiaomi/Chromecast, handshake VPN,
pedido HTTPS através de uma VPN real, indexação, filme, isolamento de portas
ou revogação durante reprodução. **SEC-01…12 continuam por executar.**
A ausência desses resultados não é substituída por mocks ou compilação.

A base suporta vários Android TV/Google TV por capacidades; Xiaomi Box S2 e
Chromecast são aparelhos de aceitação, sem limitar o produto a essas marcas.
Seguem-se M0 (prova dos três motores), M2 (wizard/bibliotecas/TrueNAS), M3
(identidade/associação) e M4 (primeiro filme local na TV). O suporte remoto
integral continua condicionado a M5/M6 do
[roadmap](ROADMAP_INSTALACAO_SERVER_TV_v0_2.md).
