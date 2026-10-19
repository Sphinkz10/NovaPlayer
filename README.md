# NOVA Platform / NovaPlayer

Plataforma privada de cinema auto-hospedado (em desenvolvimento).

**Estado atual:** [fecho consolidado da M3](docs/M3_FECHO.md). Servidor com configuração Jellyfin e cliente Android de laboratório com identidade, login Directory e permissões. A M3 está em validação integrada; o documento contém os critérios únicos e as provas exigidas.

O proprietário configura o NOVA Server e aprova as TVs. O familiar usa a própria conta Directory. Catálogo e reprodução chegam na M4; WireGuard, Tailscale e NetBird nativos pertencem à M5. Ainda não há ensaio físico no TrueNAS, Xiaomi Box S2 ou Chromecast.

- [Estado e limites](docs/ESTADO_REAL.md).
- [Roadmap até instalar e ver filmes](docs/ROADMAP_INSTALACAO_SERVER_TV_v0_2.md).
- [Contrato de integração nativa](docs/ADR_001_CONNECT_NATIVO.md).
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

As execuções e os pacotes atuais são registados em [M3_FECHO.md](docs/M3_FECHO.md). Os ZIPs originais em `archives/` preservam o histórico e não recebem as alterações atuais.
