# Tasks — cliente e parser do Instagram

## 1. Cliente

- [ ] 1.1 `whatbot/channels/instagram.py` implementando o contrato de canal
      sobre `graph.instagram.com`
      (→ Requirement "Cliente Instagram implementa o contrato de canal")
- [ ] 1.2 Causas tipadas de `ChannelError` disponíveis para uso por quem
      chama o cliente: janela de mensageria expirada (`window_expired`),
      permissão de atendimento humano ausente, rate limit com backoff. Este
      change define o mecanismo; a política de **quando** levantar
      `window_expired` (consulta a `last_inbound_at`) é implementada por
      `instagram-messaging-window`, que edita este mesmo arquivo depois
      (→ Requirement "Erros de canal são identificados por tipo")
- [ ] 1.3 Quebra de mensagem longa em blocos, preservando ordem
      (→ Requirement "Mensagem longa é dividida preservando ordem")

## 2. Parser

- [ ] 2.1 `whatbot/instagram_webhook.py`: parser de mensagem comum,
      produzindo `InboundMessage`
      (→ Requirement "Parser reconhece formatos e casos de borda do
      Instagram")
- [ ] 2.2 Reconhecimento de eco da secretaria pelo app do Instagram
      (→ idem, cenário "Eco da secretaria pelo app do Instagram")
- [ ] 2.3 Menção e resposta a story, mensagem só com mídia, mensagem apagada
      (→ idem, cenários correspondentes)
- [ ] 2.4 Múltiplos eventos num único POST
      (→ idem, cenário "Múltiplos eventos num POST")

## 3. Testes

- [ ] 3.1 `tests/test_instagram_client.py`: envio normal, quebra de mensagem
      longa, cada causa de `ChannelError`, sem rede (`requests` mockado)
- [ ] 3.2 `tests/test_instagram_webhook.py`: parser para cada formato e cada
      caso de borda listado no requirement, sem rede
- [ ] 3.3 Estender `tests/test_channel_contracts.py` para verificar que o
      cliente Instagram satisfaz o protocolo `ChannelClient`, mesma
      verificação já aplicada ao cliente WhatsApp
- [ ] 3.4 Suíte completa verde
