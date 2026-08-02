# Fila mostra canal e identificador legível

## Why

`whatbot/channels/base.py` já expõe `channel_label()`. Quando o Instagram
entrar em produção, a secretaria precisa saber por qual app responder — é o
risco número um do projeto segundo `docs/INSTAGRAM_INTEGRATION_PLAN.md`.

**Atualização pós-`identity-multichannel`**: a parte do rótulo legível
(nome → handle → identidade externa) **já foi consumida** em
`whatbot/queue.py` durante a implementação daquele change — foi necessário
porque `contact.phone` virou `NULL` fora do WhatsApp, e as notificações que
antes imprimiam `contact.phone` cru precisavam de um substituto imediato
para não quebrar. Ver `openspec/changes/identity-multichannel/design.md`,
Decisão 8.

O que **falta** e é o escopo real deste change agora: indicar o **canal**
de origem junto ao rótulo (ex.: "via Instagram"), usando `channel_label()`
— que segue órfão de qualquer consumidor de produção.

## What Changes

- `whatbot/queue.py`: notificações de novo item na fila, listagem da fila e
  resumo diário passam a indicar o canal (`channel_label()`) ao lado do
  rótulo legível que `identity-multichannel` já introduziu.
- Nenhuma mudança de schema ou de contrato de canal — só consumo do que já
  existe.

## Impact

- Specs afetadas: `identity` (consumo do requisito "Rótulo legível de
  contato", que ganha um cenário novo de uso na fila)
- Código alterado: `whatbot/queue.py`
- Testes alterados: `tests/test_queue.py`, e o caso já existente
  `test_handover_answers_customer_on_channel_and_admin_on_whatsapp` em
  `tests/test_main_e2e.py` (estendido, não recriado)
- Bloqueado por: `identity-multichannel`
- **Bloqueia `instagram-messaging-window`**: os dois changes editam a mesma
  notificação em `whatbot/queue.py` — este change introduz o rótulo/canal,
  `instagram-messaging-window` acrescenta o prazo de resposta na mesma
  string. Precisa ser feito antes, para não haver duas edições concorrentes
  do mesmo trecho.
- Não depende de nenhum change de Instagram além da fundação — pode ser
  feito logo após `identity-multichannel`, sem esperar cliente ou ingestão
  do Instagram existirem
