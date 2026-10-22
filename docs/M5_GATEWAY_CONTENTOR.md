# M5 — Gateway em Docker e configuração autenticada da TV

Implementação de 21 outubro 2026, entrega preparada em 22 outubro. Não confundir estes ensaios com as provas anteriores do worker de namespace preparado manualmente.

O gerador `server/scripts/wireguard_install.py` prepara uma instalação nova com cinco serviços. O `nova-gateway` cria a interface WireGuard e a firewall no seu namespace Docker; apenas `nova-client` partilha essa rede. Admin, Directory e Jellyfin conservam os seus processos e permissões. A imagem do gateway e a do Core exigem digests explícitos.

A firewall aceita apenas o HTTPS de cliente destinado ao IP privado do gateway e aos endereços de TV aprovados. A lista possui expiração no kernel, aplicada a entrada e saída, antes de qualquer regra genérica de ligações estabelecidas. Sem renovação, a autorização expira em até 13 segundos após a última aplicação. A saída normal remove a interface; Docker reinicia o processo após falha. Um namespace retido por `nova-client` não depende da sobrevivência do Python para expirar acesso. Não há encaminhamento para outras redes.

O contentor tem `NET_ADMIN` para a sua rede e `DAC_OVERRIDE`/`CHOWN` para os volumes privados partilhados com o UID do Core. Não recebe `SYS_ADMIN`, modo privileged, rede do host, socket Docker, dados de media nem estado NOVA/Directory. Requer suporte WireGuard/nftables no kernel do NAS; não instala pacotes no TrueNAS. A abordagem usa [partilha de rede e capacidades do Compose](https://docs.docker.com/reference/compose-file/services/) e [elementos nftables com timeout](https://wiki.nftables.org/wiki-nftables/index.php/Sets).

`GET /api/v1/device/wireguard/profile` exige a credencial da própria TV, inscrição aprovada e observação autenticada/fresca do gateway. Distribui apenas parâmetros públicos, ligados a servidor/dispositivo/chave/revisão; o perfil dura 24 horas. A TV gera a sua chave privada, guarda o perfil cifrado no Keystore, pede o consentimento VPN do Android e verifica o HTTPS NOVA com o mesmo certificado já aprovado na LAN. O certificado criado pelo gerador cobre os dois IPs.

A página inicial Android permite pedir/preparar o WireGuard, ligar, e desligar explicitamente para voltar à LAN. O catálogo/player reutiliza a sessão NOVA com o endereço do túnel; a associação persistente mantém a origem LAN e a identidade da chave local. Uma falha, expiração ou reinício da aplicação com WireGuard selecionado não escolhe LAN silenciosamente. É necessário voltar a ligar ou selecionar LAN.

## Limites da entrega

- Preparação inicial na LAN e renovação do perfil após 24 horas; o Directory ainda não fornece descoberta remota anterior ao túnel.
- WireGuard direto exige endpoint UDP alcançável; não há ainda relé NOVA nem travessia automática de CGNAT. Não expor HTTP/Jellyfin/admin do NAS na Internet.
- Atualizar/reiniciar o conjunto Compose, incluindo gateway e cliente que partilham a rede.
- O novo perfil de cinco serviços não foi incluído na recuperação LAN M4; não usar esse recuperador para promover a instalação remota a produção.
- Tailscale e NetBird continuam por integrar na jornada funcional. A compilação dos motores e o teste JNI não equivalem a autenticação/reprodução pelos fornecedores.
- TrueNAS/Xiaomi/Chromecast físicos e SEC-01…12 mantêm-se pendentes. M5 completa continua aberta.

## Ensaios adicionados

1. Testes de API: autenticação, isolamento por dispositivo, aprovação, expiração/indisponibilidade, revogação, destino/porta e ausência de rotas administrativas.
2. Docker real: instalação gerada, peer WireGuard, TLS 1.3, catálogo/vídeo Range Jellyfin pelo túnel, bloqueio de HTTPS existente/novo com gateway congelado, recuperação, endereço estável e revogação.
3. Android API 26/35: obtenção real de perfil pela API, rejeição de parâmetros adulterados, consentimento nativo, verificação da identidade, catálogo por D-pad, primeiro frame Media3, avanço/pausa/retoma pelo túnel e mudança explícita entre túnel e LAN. Vídeo sintético servido por fixture Jellyfin HTTP; a imagem Jellyfin real é coberta pelo ensaio Docker complementar.
4. Reinício do processo Android com WireGuard selecionado: a sessão persistente conserva a identidade de associação e bloqueia a utilização implícita da LAN até uma escolha explícita do utilizador.

## Resultados deste incremento

Código executável `88efc1ac78ce500b946088925f3b4a9dde08a118`; merge de CI `0211e08bb06e5bb3ab4c1ae2a2e3bb118c8052ea`, com árvores iguais.

| Ensaio | Resultado |
|---|---|
| Python Linux 3.12/3.13 | 383/383 em cada ambiente |
| Python Windows 3.12/3.13 | 375 aprovados + 8 exclusões POSIX em cada ambiente |
| Kotlin / compilação / lint | 203 testes, compilação e lint aprovados |
| CI principal | 8/8 jobs, incluindo imagem Core, Docker, recuperação LAN e dependências |
| Gateway gerado em Docker | 9/9 verificações remotas e 12/12 LAN |
| WireGuard Android API 26 | 37/37, incluindo reprodução Media3 e reinício sem regresso implícito à LAN |
| WireGuard Android API 35 | 37/37, incluindo reprodução Media3 e reinício sem regresso implícito à LAN |
| Associação/player LAN e distribuição/update | API 26 e 35 aprovadas |

Execuções: [principal](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39686627739), [gateway Docker](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39686627904), [WireGuard Android](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39686627658), [associação/player](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39686627866), [distribuição](https://github.com/Sphinkz10/NovaPlayer/actions/runs/39686627821).

A primeira execução Windows/Python 3.12 excedeu os 5 segundos do teste de login; a reprodução local e a repetição sem alterar o código passaram. No WireGuard API 35, uma tentativa falhou ao descarregar o emulador e a seguinte teve `ConnectException` na inscrição inicial, antes do túnel. A terceira tentativa, sem alterações ao código ou aos critérios, passou as 37 verificações. As falhas ficam registadas e não são contadas como aprovações. Resultado final: **15/15 jobs aprovados** nas cinco execuções acima.

Imagens publicadas, com acesso anónimo ao manifesto confirmado:

```text
ghcr.io/sphinkz10/nova-core@sha256:df81531295f63af71c2f9e3e8afb386ad9a7784e421d7d7407e3c812a163176c
ghcr.io/sphinkz10/nova-gateway@sha256:ba5b24a1aa84437c7fbae8955e3e36233a2ba78801b6ddfdb91bfb6ba0d09401
```

A APK 0.10 foi compilada localmente a partir do mesmo código, com versionCode 10, e assinada com a identidade persistente da 0.9. SHA-256: `d4d7851cb53abb891b6bf3ff816ccb3d9ef8f0655161d325f2a2d737e7cb9403`. Não depurável, mínimo API 26, quatro ABIs e alinhamento de 16 KB verificados. Os ensaios de instrumentação usam uma APK debug descartável; não são execução física desta APK assinada.

[Guia de instalação](M5_INSTALACAO_WIREGUARD.md) · [Resultados e proveniência](M5_GATEWAY_RESULTADOS.json) · [Oito capturas reais](screenshots/wireguard-88efc1a/index.html). A pasta local de entrega é `NOVA_M5_GATEWAY_2026-10-22`; inclui APK, ZIP de fontes, digests das duas imagens, resultados e hashes. O incremento WireGuard Docker/TV está concluído em laboratório. Os limites listados acima mantêm a M5 completa aberta.
