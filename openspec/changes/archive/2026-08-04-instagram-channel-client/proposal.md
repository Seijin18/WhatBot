# Cliente e parser do Instagram

## Why

`whatbot/channels/` já define o contrato de canal (`ChannelClient`,
`ChannelError`, `InboundMessage`) e o WhatsApp o implementa em
`whatsapp_evolution.py`. Não existe ainda a implementação para Instagram: sem
`whatbot/channels/instagram.py`, sem parser de webhook, sem tratamento dos
casos de borda do Instagram Direct (eco da secretaria, menção a story, mídia
sem texto, mensagem apagada, múltiplos eventos por POST).

A spec do change monolítico original (removido, ver commit `5774965`) já
continha os requisitos de janela e de idempotência, mas faltavam os
requisitos do próprio protocolo do cliente — por isso tarefas como "quebra
de mensagem longa" e "casos de borda do parser" existiam sem requirement
correspondente. Este change fecha essa
lacuna.

## What Changes

- `whatbot/channels/instagram.py`: implementa `ChannelClient` sobre
  `graph.instagram.com` (Instagram API with Instagram Login — ver
  `design.md`).
- Erros tipados sobre `ChannelError`: janela expirada, permissão ausente,
  rate limit com backoff.
- Mensagem longa é dividida em blocos, preservando ordem de entrega.
- `whatbot/instagram_webhook.py`: parser de mensagem e de eco, produzindo
  `InboundMessage` (reaproveitando o contrato que `harden-channel-layer` já
  estabeleceu para o WhatsApp).
- Casos de borda tratados explicitamente: eco da própria secretaria
  respondendo pelo app do Instagram, menção e resposta a story, mensagem só
  com mídia (sem texto), mensagem apagada, múltiplos eventos num único POST
  do webhook.

Este change entrega o **contrato** de erro de janela (a causa
`window_expired` como um dos valores possíveis de `ChannelError`), não a
**política** de quando levantá-lo. `InboundMessage` (canal, `external_id`)
já é produzido só com o que está em `whatbot/channels/base.py`
(`harden-channel-layer`), sem tocar `db.py` — por isso este change não
precisa da migração de identidade para existir. A política real (consultar
`last_inbound_at`, decidir dentro ou fora da janela) é implementada por
`instagram-messaging-window`, que edita o mesmo arquivo
`whatbot/channels/instagram.py` depois que este change o cria — ver
`instagram-messaging-window/design.md`.

## Impact

- Specs afetadas: `instagram`
- Código novo: `whatbot/channels/instagram.py`, `whatbot/instagram_webhook.py`
- Testes novos: `tests/test_instagram_client.py`,
  `tests/test_instagram_webhook.py` — ambos sem rede, `requests` mockado,
  seguindo o padrão de `tests/test_evolution_client.py`
- Testes estendidos: `tests/test_channel_contracts.py` (cliente Instagram
  satisfaz o protocolo `ChannelClient`, mesma verificação já aplicada ao
  cliente WhatsApp)
- **Não bloqueado por `identity-multichannel`** — o cliente e o parser não
  tocam `db.py`; podem ser desenvolvidos em paralelo com a fundação, desde
  o primeiro dia.
- Bloqueia: `instagram-messaging-window` (edita o arquivo que este change
  cria), `instagram-ingestion-service` (usa o parser para montar o payload)
