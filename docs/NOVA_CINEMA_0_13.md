# NOVA Cinema 0.13 — revisão da experiência TV

**Validada em laboratório nas APIs 26 e 35; APK 0.13 assinada para teste.** Esta revisão substitui o início centrado em configuração por um
ecrã de cinema com destaque e uma fila de títulos reais da conta. Não introduz
filmes de demonstração nem permissões novas na aplicação.

- Início: títulos da primeira biblioteca autorizada; abrir um título conduz ao
  detalhe. Conta, ligação e configuração ficam na barra superior.
- Catálogo: capas com proporção de poster, nomes e progresso de reprodução,
  categorias compactas e foco com contorno e ampliação moderada.
- Detalhe: capa separada da sinopse, metadados e ação clara de reproduzir/retomar.
- Ecrãs em paisagem, com a barra de estado removida; navegação por comando.
- Voltar preserva o título focado. Regressar ao início volta a verificar a conta;
  os títulos e imagens anteriores são descartados durante a saída/revalidação.

A APK normal continua LAN/WireGuard. Este trabalho visual não conclui a M5,
não instala o gateway Tailscale nem implementa NetBird. O servidor e o contrato
de confiança não mudam. A versão usa o mesmo pacote e identidade de assinatura
persistente; os ensaios CI usam identidades de assinatura descartáveis.

Validação concluída: build/lint, instalação/atualização API 26/35, associação,
reprodução LAN/WireGuard e regressão da variante Tailscale. O percurso por comando
inclui abrir o destaque do início e voltar à grelha, além de reprodução,
pausa/retoma e recuperação do foco. As capturas foram recolhidas na app real, com biblioteca e vídeo sintéticos. [Resultados e proveniência](NOVA_CINEMA_0_13_RESULTADOS.json): 17/17 jobs aprovados. A compilação release local teve zero erros de lint e 63 avisos, sem supressões novas.

A APK usa o mesmo certificado público da 0.12 e pode atualizá-la sem desinstalar. As imagens de servidor/gateway estão fixadas por digest no relatório; a chave privada de assinatura fica fora do Git e da CI.
