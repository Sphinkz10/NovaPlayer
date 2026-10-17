# Ensaio de compilação dos motores nativos (M0)

Workflow `native-engines.yml`: compila num runner Linux um único AAR gomobile
com os pacotes Tailscale e NetBird, depois tenta incluí-lo na APK NOVA que já
contém WireGuard. Uma única geração evita duplicar a classe `go.Seq` e a
biblioteca `libgojni.so`.

Compilação aprovada em [39069358627](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39069358627): AAR conjunto e APK com WireGuard construídos com sucesso.
O primeiro [teste de runtime](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39074565825)
passou em API 26 nas duas ordens, mas API 35 sofreu SIGSEGV quando gomobile foi
carregado antes de WireGuard no mesmo processo. A ordem inversa passou.

A revisão seguinte move gomobile para um serviço privado `:nova_overlay` dentro
da mesma APK. A instrumentação exige PIDs diferentes e testa ambas as ordens em
API 26 e 35, com processos novos. Essa revisão não carrega os dois runtimes Go
no mesmo processo; as quatro combinações passaram em
[39074985057](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39074985057).
O serviço de prova só existe no build debug experimental, não na APK normal.
Os dois emuladores são x86_64; isto não prova execução ARM ou funcionamento numa TV física.
Não inicia túneis, não recebe credenciais e não prova HTTPS. O registo Android
continua a marcar Tailscale/NetBird como não implementados até existir ponte e
teste de funcionamento. Uma compilação bem-sucedida só fecha o risco de build.

Fontes exatas, NDK/API, gerador mobile, hashes de módulos, licenças de topo e
log são preservados nos artefactos temporários do job. Antes da distribuição,
rever também as licenças transitivas e as restrições de todos os componentes.
Os fontes upstream não são copiados para o repositório NOVA.

Este ensaio usa três ABIs: ARM64, ARMv7 e x86_64 de emulador. A primeira prova
de rede exige adicionar a ponte Kotlin/VpnService, armazenamento de estado,
inscrição por dispositivo e servidor HTTPS de teste. Nenhuma conta externa
é criada automaticamente.

Os artefactos da CI expiram após sete dias. Para repetir o teste mais tarde,
executar `native-engines.yml` e indicar o ID dessa execução bem-sucedida no
campo `native_build_run` de `native-runtime.yml`. O teste recusa dispositivos
físicos e execução fora da CI, e guarda resultados por ordem, logcat e crash buffer.
