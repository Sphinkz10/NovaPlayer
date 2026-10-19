# M3 — cliente Android de associação, laboratório 0.5

> Histórico de incremento. Para o estado, comportamento e instalação atuais, consultar [M3_FECHO.md](M3_FECHO.md). As limitações descritas abaixo referem-se à revisão histórica indicada neste guia.

O cliente Android agora importa a identidade pública de um NOVA Server, apresenta um código, aguarda aprovação no Control e conserva uma sessão cifrada entre aberturas. Este incremento não entrega ainda catálogo, reprodução, Directory ou túneis VPN reais.

## Confiança inicial neste ensaio

O proprietário exporta um ficheiro JSON público, válido durante 24 horas, com origem HTTPS privada, UUID NOVA e certificado público do serviço cliente. **Não é um convite assinado nem uma autorização de acesso.** A sua impressão digital SHA-256 completa deve ser transmitida por um canal de confiança e comparada na TV antes de confirmar. O ficheiro sozinho não autentica quem o enviou. Nunca aceitar ficheiros e impressões digitais de uma pessoa não autorizada.

A app importa o ficheiro através do seletor de documentos Android, sem pedir acesso geral ao armazenamento. Mostra a identidade e a impressão digital e exige confirmação. Só então contacta o servidor e apresenta o código de dez minutos, que o proprietário consulta e aprova no Control.

A ligação exige HTTPS, origem IPv4 privada/overlay ou loopback explícita com porta, certificado exato confirmado, cadeia e validade aceites e hostname correspondente. Não há aceitação automática de certificados, troca de pin, redirecionamentos ou fallback HTTP. DNS e IPv6 ainda não fazem parte deste bootstrap de laboratório. O certificado confiado é local a esta ligação; a app não altera a trust store do Android.

A descoberta e o bootstrap sem transferência de ficheiros dependem da integração Android com o [Directory de laboratório](M3_DIRECTORY_LAB.md), cujo serviço já existe. Essa integração continua pendente. Este procedimento não é a experiência final para familiares.

## Sessão e revogação

- Credenciais e identidade guardadas com AES-256-GCM e chave Android Keystore, numa área privada distinta dos perfis VPN. Backup e transferência estão desativados na aplicação. Não prometer proteção hardware em todos os equipamentos.
- A reabertura verifica a autorização no servidor. Sem rede, conserva o estado local mas mostra indisponibilidade; não declara o dispositivo autorizado para usar media.
- Renovações são serializadas pelo controlador partilhado da app. Antes de renovar, grava um marcador durável. Se o processo terminar ou a resposta for perdida, não reutiliza o refresh anterior: exige nova associação. Uma resposta recebida e persistida pode ser verificada quando a rede voltar.
- Uma revogação no Control invalida access/refresh. Na próxima verificação online, a app elimina a associação rejeitada. Ainda não há sessão de vídeo para terminar.
- “Esquecer associação nesta TV” apaga o estado local e tenta revogar a sessão no servidor. Se estiver offline ou o access token já expirou, o proprietário deve revogar pelo Control; não prometer revogação remota nessa situação.
- Certificado alterado/inválido e identidade diferente bloqueiam a ligação. Não existe renovação automática do pin: o proprietário terá de fornecer nova identidade e o utilizador confirmar uma nova associação.

## Ensaiar com servidor no PC

1. Usar as fontes atuais do servidor, criar o proprietário e seguir [M3 do servidor](M3_ASSOCIACAO_DISPOSITIVOS.md). Iniciar o processo cliente com certificado/chave locais válidos, origem como `https://127.0.0.1:8920` e certificado com SAN para `127.0.0.1`.
2. Exportar a identidade, a partir de `server/`:

   ```text
   python scripts/device_invitation.py --state CAMINHO_ESTADO_NOVA --origin https://127.0.0.1:8920 --certificate CAMINHO_CERTIFICADO_PUBLICO.pem --output nova-ligacao.json
   ```

   O comando recusa sobrescrever ficheiros e imprime a impressão digital. Nunca distribuir a chave TLS privada, token do proprietário ou credenciais do fornecedor VPN.
3. Instalar a APK debug de laboratório num emulador/aparelho de teste. Para alcançar o serviço do PC através de uma ligação ADB já autorizada, usar `adb -s SERIAL reverse tcp:8920 tcp:8920`. Escolher explicitamente o aparelho correto. A origem dentro da app mantém-se `https://127.0.0.1:8920`.
4. Disponibilizar o JSON no seletor de documentos do aparelho. Abrir “Associar ao NOVA Server”, importar, comparar a impressão digital completa com o valor do proprietário e confirmar. Não digitar IPs, chaves VPN ou palavras-passe administrativas na TV.
5. No Control do PC, introduzir o código apresentado pela app, conferir o pedido e aprovar. A app confirma a associação. Fechar/reabrir e revogar pelo Control para testar persistência e bloqueio.
6. No fim do ensaio, esquecer/revogar o dispositivo e remover apenas o redirecionamento criado: `adb -s SERIAL reverse --remove tcp:8920`.

O serviço cliente continua limitado a loopback e não é publicado pelo Compose/gerador TrueNAS. Sem ADB/túnel de laboratório, a APK ainda não alcança esse endpoint a partir de outra máquina. Alguns Android TV não disponibilizam seletor de documentos: a app apresenta essa limitação; é necessário um fornecedor de documentos para este ensaio. O teste não instala nem configura esses fornecedores automaticamente.

## Verificação

Resultado de 19-10-2026: código `abe56f0a1881314752e0555520dbbf4d8ce286b5`, [CI Android 39220853687](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39220853687), API 26 e 35 aprovadas, com 11 etapas em cada emulador. Cada artefacto conserva a APK exata e o seu SHA-256 no relatório. Os jobs compilam separadamente e usam assinaturas debug próprias; não são o mesmo binário. A APK entregue corresponde à execução API 35.

O ensaio sincroniza apenas o relógio dos emuladores descartáveis e coloca a interação em modo de comando. Isto corrigiu falhas da preparação do ensaio sem relaxar as verificações de prazo/certificado da app. A recolha de logs não bloqueia o teste se um Android antigo recusar limpar um buffer.

- Núcleo JVM: políticas, transporte e máquina de estados, incluindo escrita antes de refresh, respostas perdidas, concorrência, identidade, expiração e TLS real.
- Android: build da APK e instrumentação, lint e prova em emuladores API 26/35. O teste usa aprovação pelo servidor real, TLS, confirmação com D-pad, armazenamento cifrado/Keystore, force-stop/reabertura, renovação, revogação, interrupção e adulteração do ciphertext.
- A importação de ficheiro no ensaio automatizado injeta os mesmos bytes na revisão da Activity; não automatiza o seletor de documentos do fabricante. Hardware Xiaomi Box S2/Chromecast e outros Android TV continuam por testar.
- `connect/scripts/smoke_pairing_android.py` recusa aparelhos físicos e execução fora da CI. A credencial do proprietário fica no processo de teste do PC; não entra na APK nem nos relatórios.

Não existem resultados físicos da TV ou NAS. A APK é debug de laboratório, não uma release assinada para utilização familiar. A APK normal mantém WireGuard; os três motores juntos continuam a ser uma compilação experimental separada.

## Próximo marco

Integrar na TV o Directory, que já implementa registo/prova de posse e descoberta autenticada; concluir confiança TLS inicial/renovação integrada e permissões por utilizador/biblioteca. Depois, M4: catálogo, navegação e primeiro filme local. A aceitação física M2 no TrueNAS permanece pendente.

Referências de implementação: [Android Keystore](https://developer.android.com/privacy-and-security/keystore), [criptografia Android](https://developer.android.com/privacy-and-security/cryptography), [Storage Access Framework](https://developer.android.com/training/data-storage/shared/documents-files).
