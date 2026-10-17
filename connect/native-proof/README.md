# Ensaio de compilação dos motores nativos (M0)

Workflow `native-engines.yml`: compila num runner Linux um único AAR gomobile
com os pacotes Tailscale e NetBird, depois tenta incluí-lo na APK NOVA que já
contém WireGuard. Uma única geração evita duplicar a classe `go.Seq` e a
biblioteca `libgojni.so`.

Estado: ensaio experimental em execução, sem resultado de sucesso presumido.
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
