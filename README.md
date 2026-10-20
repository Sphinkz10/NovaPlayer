# NOVA Platform / NovaPlayer

Plataforma privada de cinema auto-hospedado (em desenvolvimento).

**Estado atual:** [M4 — Instalação LAN](docs/M4_INSTALACAO_LAN.md) reúne assistente de instalação nova no TrueNAS, configuração na própria TV, contas de familiares e catálogo/player. Resultados e limites estão nesse guia. A [M3 de identidade e permissões](docs/M3_FECHO.md) está concluída em laboratório. Aceitação física, assinatura definitiva e recuperação integrada do perfil LAN mantêm a M4 aberta.

O proprietário configura o NOVA Server e aprova as TVs. O familiar usa a própria conta Directory. WireGuard, Tailscale e NetBird nativos pertencem à M5. Ainda não há ensaio físico no TrueNAS, Xiaomi Box S2 ou Chromecast.

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

Em Windows usar `gradlew.bat`; os testes de navegador aceitam `--channel msedge`, usado também no runner Windows da CI. Os testes POSIX de permissões/caminhos são executados em Linux. Os gates Docker são `python server/scripts/smoke_compose.py` e `python server/scripts/smoke_lan_compose.py`, num anfitrião Linux descartável com Docker; o primeiro exige portas 8096/8787 livres.

O pacote atual e as execuções são registados em [M4_INSTALACAO_LAN.md](docs/M4_INSTALACAO_LAN.md); a prova anterior do player está em [M4_CINEMA_LOCAL.md](docs/M4_CINEMA_LOCAL.md). Os ZIPs originais em `archives/` preservam o histórico e não recebem as alterações atuais.
