# Ensaio de compilação dos motores nativos (M0)

Workflow `native-engines.yml`: compila num runner Linux um único AAR gomobile
com os pacotes Tailscale e NetBird, depois tenta incluí-lo na APK NOVA que já
contém WireGuard. Uma única geração evita duplicar a classe `go.Seq` e a
biblioteca `libgojni.so`.

Compilação aprovada em [39069358627](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39069358627): AAR conjunto e APK com WireGuard construídos com sucesso.
O workflow separado native-runtime.yml testa o carregamento JNI em emuladores
API 26 e 35, nas duas ordens possíveis, com processos novos. Resultado de
runtime ainda pendente; não inferir sucesso a partir da compilação.
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
