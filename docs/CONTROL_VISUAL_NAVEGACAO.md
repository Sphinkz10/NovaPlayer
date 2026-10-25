# NOVA Control — revisão visual e de navegação

25 de outubro de 2026. Incremento do servidor após a entrega Cinema 0.13.

O proprietário deixa de percorrer uma página com todos os formulários. O Control
passa a ter navegação persistente para Visão geral, Bibliotecas, Pessoas e TVs,
Directory e Ligação privada. O início reúne diagnóstico e atalhos para preparar
a instalação. O login desaparece ao entrar e reaparece ao terminar a sessão ou
quando a API devolve sessão expirada.

Os menus funcionam por rato, toque e teclado. Voltar/Avançar do navegador repõe o
ecrã, a seleção no menu e o foco no título. Uma atualização da página exige login
novamente; o endereço guarda apenas o nome da área, sem credenciais. O layout
adapta-se a computador e telemóvel. Os estados dos serviços continuam a vir da API.

Validação local em Edge: bootstrap, login, navegação, permissões de bibliotecas,
aprovação/revogação de TVs, publicação/renovação Directory e aprovação/desativação
do perfil Tailscale. Os testes incluem respostas tardias após logout, ausência de
armazenamento de sessão no navegador, injeção de HTML e ecrãs sem overflow
horizontal a 1280, 390 e 320 px. Também passaram 42 testes de API/dispositivos.
Os quatro percursos de navegador preservam as verificações funcionais anteriores.

A pré-visualização exportada pelo teste é uma cópia inerte da interface real com
dados descartáveis: só a navegação funciona; os campos e operações ficam
desativados, sem chamadas de rede ou acesso ao NAS. As capturas do servidor
local e a pré-visualização têm propósitos distintos e estão identificadas na entrega.

Este incremento altera apenas o Control e os seus testes. A APK continua na
versão 0.13. Não inclui uma nova imagem Docker instalada nem validação física no
TrueNAS, Xiaomi ou Chromecast. A integração completa de Tailscale e NetBird e a
revisão adicional da experiência TV continuam por concluir.
