# NOVA Platform / NovaPlayer

Plataforma privada de cinema auto-hospedado (em desenvolvimento).

Base em desenvolvimento: **NOVA Server P01 v0.1.1** e **NOVA Connect laboratório v0.4**, especificações técnicas, segurança e referências Figma. Os ZIPs de origem permanecem em `archives/`.

> **Estado:** provas de conceito e documentação. Não é uma aplicação Android TV final, não inclui credenciais, nem está certificado para exposição na Internet. O NOVA Directory e a reprodução remota ainda não estão implementados.

O NOVA Server destina-se a proprietários dos ficheiros; o NOVA Cinema destina-se a familiares/utilizadores autorizados. O Jellyfin é um serviço integrado no pacote proposto.

Esta primeira fase corrige login do Control, diagnóstico Jellyfin, concorrência do login e dependências Python. Acrescenta rascunhos autenticados para três fornecedores, contratos Android independentes de marcas, build com Gradle Wrapper, locks/checksums e workflows de testes Linux/Windows/Android/Docker.

WireGuard tem um motor Android compilado. **Tailscale e NetBird ainda não têm motores incorporados**, e guardar configurações não ativa ligações. A APK é de diagnóstico, sem biblioteca/player. Compatibilidade inicial por capacidades: Android API 26+, quatro ABIs WireGuard, sem exigir uma marca específica.

- [Entrega e verificações da fase 1](docs/FASE_1_RESULTADOS.md).
- [Contrato de integração nativa](docs/ADR_001_CONNECT_NATIVO.md).
- [Roadmap até instalar servidor e TV](docs/ROADMAP_INSTALACAO_SERVER_TV_v0_2.md).
- [Servidor](server/README.md) e [Android](connect/README.md).

Validação local (Python 3.12/3.13; JDK 17 e Android SDK 35):

```sh
python -m pip install --require-hashes -r server/requirements-dev.txt
cd server
python -m pytest -q
python scripts/smoke_http.py
python -m playwright install chromium
python scripts/smoke_browser.py
cd ../connect
bash gradlew :core:verifyCore :app:assembleDebug :app:lintDebug
```

Em Windows usar `gradlew.bat`; o teste de navegador aceita `--channel msedge` quando o Edge já está instalado. Os quatro testes de permissões/caminhos do instalador são exclusivos de Linux. O gate Docker de laboratório é `python server/scripts/smoke_compose.py`, num anfitrião Linux com Docker e portas 8096/8787 livres.

A [CI de integração](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39069361596) já aprovou Linux, HTTP, navegador e Docker real: dois mounts legíveis com escrita bloqueada, reinício e persistência de proprietário/sessão. M0 exige ainda provar os três motores nativos com HTTPS real; M2 exige wizard/bibliotecas e validação no TrueNAS.
