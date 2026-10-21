# M5 — Gateway em Docker e configuração autenticada da TV

Implementação de 21 outubro 2026. Os resultados deste incremento serão registados após a execução dos ensaios Docker/Android; não confundir com as provas anteriores do worker de namespace preparado manualmente.

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
3. Android API 26/35: obtenção real de perfil pela API, rejeição de parâmetros adulterados, consentimento nativo, verificação da identidade e mudança explícita da sessão Cinema entre túnel e LAN.

Estes critérios descrevem os ensaios implementados. Consultar os resultados da execução antes de interpretar qualquer um como aprovado.
