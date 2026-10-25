# NOVA Cinema 0.14 — navegação comum e pesquisa por comando

Candidata em validação. A entrega assinada anterior continua na 0.13 até serem
recolhidos os resultados desta revisão.

- Menu lateral persistente no início, bibliotecas, catálogo e detalhe: Início,
  Bibliotecas, Pesquisar, Conta, Ligação e Configurar.
- Identidade visual escura com o mesmo acento do Control, destaque com metadados
  e ação para abrir o título selecionado. A biblioteca tem uma entrada própria;
  deixa de depender do botão do destaque.
- A pesquisa do início abre a primeira biblioteca autorizada e coloca o foco no
  campo. Sem associação segue o percurso existente de configuração/login. Com
  várias bibliotecas, a pesquisa do catálogo atua na biblioteca aberta.
- Capas com foco próprio sem o retângulo cinzento adicional do botão Android.
  A grelha calcula as colunas descontando o espaço do menu lateral.
- O detalhe identifica a biblioteca, separa capa/sinopse e mantém reproduzir,
  retomar, áudio e legendas no percurso existente do leitor.

Os títulos, metadados e imagens continuam a vir da conta autorizada; não existe
catálogo de demonstração no produto. Ao sair, o início descarta o conteúdo e
volta a autorizar no regresso. Nenhum fornecedor ou permissão foi ativado por
esta alteração visual.

A instrumentação conserva os testes de reprodução, progresso e revogação e
acrescenta o botão do destaque e a sequência real Baixo/Baixo/OK no menu para
abrir a pesquisa com foco no campo. A distribuição ensaia 14 → 15 com chaves
descartáveis; a entrega usa a assinatura persistente guardada fora do Git.

O Control desta revisão também corrige a espera do teste de exportação da
pré-visualização: uma asserção do Playwright substitui a expressão avaliada que
o Chromium Linux recusava pela CSP. A política de segurança mantém-se.

LAN/WireGuard continuam na APK normal; Tailscale é variante de laboratório e
NetBird continua incompleto. Não substitui aceitação física em TrueNAS, Xiaomi
Box S2 e Chromecast, nem conclui a M5 ou as 12 validações finais de segurança.
