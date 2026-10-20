# NOVA Platform / NovaPlayer

Plataforma privada de cinema auto-hospedado (em desenvolvimento).

**Estado atual:** [M4 — Distribuição Android](docs/M4_DISTRIBUICAO_ANDROID.md) prepara a NOVA Cinema com identificador próprio, debug desativado e assinatura persistente offline. O [perfil LAN com recuperação integrada](docs/M4_RECUPERACAO_LAN.md) continua aplicável. Resultados e limites estão no guia de distribuição. A [M3 de identidade e permissões](docs/M3_FECHO.md) está concluída em laboratório. A aceitação física mantém a M4 aberta.

O proprietário configura o NOVA Server e aprova as TVs. O familiar usa a própria conta Directory. WireGuard, Tailscale e NetBird nativos pertencem à M5. Ainda não há ensaio físico no TrueNAS, Xiaomi Box S2 ou Chromecast.

**Desenvolvimento M5:** após a [primeira prova de rede WireGuard](docs/M5_WIREGUARD_REDE.md), a [inscrição por TV](docs/M5_INSCRICAO_WIREGUARD.md) gera a chave no Android e permite aprovação/revogação no Control. O gateway instalável e os percursos remotos completos dos três fornecedores continuam por implementar. A entrega de instalação permanece a 0.9 LAN.

**Servidor LAN atualizado:** usar as fontes/imagem do incremento M5 para obter a correção do arranque SQLite e `certifi` atualizado. A APK assinada 0.9 é reutilizada; as imagens/locks das entregas anteriores conservam as versões históricas.

**Desenvolvimento M5:** [serviço WireGuard](docs/M5_SERVICO_GATEWAY.md) com canal local autenticado, leases de IP duráveis, reconciliação restrita e observação temporária no Control. O provisionamento/instalador e supervisor para NAS, parâmetros da TV e percurso remoto completo continuam pendentes. [Capturas reais das apps](docs/PRINTS_APPS.md), com conteúdo sintético e interface provisória.

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

O pacote atual e as execuções são registados em [M4_DISTRIBUICAO_ANDROID.md](docs/M4_DISTRIBUICAO_ANDROID.md); as provas anteriores estão nos guias de recuperação, instalação LAN e player. Os ZIPs originais em `archives/` preservam o histórico e não recebem as alterações atuais.
