# Tasks — cliente e parser do Instagram

## 1. Cliente

- [x] 1.1 `whatbot/channels/instagram.py` implementando o contrato de canal
      sobre `graph.instagram.com`
      (→ Requirement "Cliente Instagram implementa o contrato de canal")
- [x] 1.2 Causas tipadas de `ChannelError` disponíveis para uso por quem
      chama o cliente: janela de mensageria expirada (`window_expired`),
      permissão de atendimento humano ausente, rate limit com backoff. Este
      change define o mecanismo; a política de **quando** levantar
      `window_expired` (consulta a `last_inbound_at`) é implementada por
      `instagram-messaging-window`, que edita este mesmo arquivo depois
      (→ Requirement "Erros de canal são identificados por tipo")
- [x] 1.3 Quebra de mensagem longa em blocos, preservando ordem
      (→ Requirement "Mensagem longa é dividida preservando ordem")

## 2. Parser

- [x] 2.1 `whatbot/instagram_webhook.py`: parser de mensagem comum,
      produzindo `InboundMessage`
      (→ Requirement "Parser reconhece formatos e casos de borda do
      Instagram")
- [x] 2.2 Reconhecimento de eco da secretaria pelo app do Instagram
      (→ idem, cenário "Eco da secretaria pelo app do Instagram")
- [x] 2.3 Menção e resposta a story, mensagem só com mídia, mensagem apagada
      (→ idem, cenários correspondentes)
- [x] 2.4 Múltiplos eventos num único POST
      (→ idem, cenário "Múltiplos eventos num POST")

## 3. Testes

- [x] 3.1 `tests/test_instagram_client.py`: envio normal, quebra de mensagem
      longa, cada causa de `ChannelError`, sem rede (`requests` mockado)
- [x] 3.2 `tests/test_instagram_webhook.py`: parser para cada formato e cada
      caso de borda listado no requirement, sem rede
- [x] 3.3 Estender `tests/test_channel_contracts.py` para verificar que o
      cliente Instagram satisfaz o protocolo `ChannelClient`, mesma
      verificação já aplicada ao cliente WhatsApp
- [x] 3.4 Suíte completa verde
- [x] 3.5 Guarda contra `limit<=0` em `split_text` (loop infinito não
      alcançável em produção hoje, mas armadilha para quem parametrizar o
      limite depois) — corrigido após revisão do critic, com teste
      `test_non_positive_limit_does_not_loop_forever`

## 4. Pendências conhecidas (não-bloqueadoras, aprovado com ressalvas)

Registradas pela revisão do critic, deliberadamente não corrigidas agora
para não travar o avanço da sequência — retomar em `instagram-go-live` ou
`instagram-operability`, conforme o caso:

- `retry_after` de rate limit só existe embutido na string de
  `ChannelError`, não como atributo estruturado. Quem for implementar
  retry de verdade (`instagram-operability`) vai precisar disso; adicionar
  `retry_after: float | None` a `ChannelError` na hora.
- Resposta de texto a um story é descartada silenciosamente pelo parser
  (classificada como `KIND_STORY`, sem `InboundMessage`) — decisão
  implícita, nunca registrada como decisão de produto. Se esse for um
  caminho de entrada relevante na prática (é comum no Instagram), revisar
  `classify_instagram_event` para tratar texto de resposta a story como
  mensagem normal.
- `send_text` não sinaliza entrega parcial quando um bloco no meio de uma
  mensagem quebrada falha — um retry ingênuo duplicaria os blocos já
  entregues. Vale considerar antes de `instagram-go-live` ligar a conta
  real.
- Classificação de causa de erro (`window_expired` vs rate limit vs
  permissão ausente) baseada em subcodes documentados só em
  `docs/INSTAGRAM_INTEGRATION_PLAN.md` — precisa validação contra tráfego
  real da API durante a homologação de `instagram-go-live`.
- Cobertura de teste do caminho `human_agent=True` através do
  `ChannelRouter` (não só direto no cliente) e de `entry` malformado no
  payload do webhook — testes adicionais recomendados, não bloqueadores.
