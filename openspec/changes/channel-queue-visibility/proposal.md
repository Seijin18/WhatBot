# Fila mostra canal e identificador legível

## Why

`whatbot/channels/base.py` já expõe `channel_label()`, mas nenhum código de
produção o chama. `whatbot/queue.py` monta notificações e listagens usando
`contact.phone` diretamente. Hoje isso só é confuso; quando o Instagram
entrar em produção, seria o risco número um do projeto segundo
`docs/INSTAGRAM_INTEGRATION_PLAN.md`: a secretaria receberia um IGSID de 17
dígitos numa notificação e não saberia por qual app responder.

Este change resolve isso com o menor escopo possível, e é demonstrável só
com WhatsApp — não depende de nenhum código de Instagram existir, só da
fundação de identidade (`identity-multichannel`).

## What Changes

- `whatbot/queue.py`: notificações de novo item na fila, listagem da fila e
  resumo diário passam a usar o rótulo legível (nome → handle → identidade
  externa) e a indicar o canal, em vez de `contact.phone` cru.
- Nenhuma mudança de schema ou de contrato de canal — só consumo do que
  `identity-multichannel` já expõe.

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
