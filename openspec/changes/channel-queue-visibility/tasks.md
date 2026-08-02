# Tasks — fila mostra canal e identificador legível

## 1. Implementação

- [x] ~~1.1 `whatbot/queue.py`: notificação de novo item na fila usa o
      rótulo legível do contato, em vez de `contact.phone` cru~~ — feito em
      `identity-multichannel` (ver `proposal.md`, Decisão 8 de
      `identity-multichannel/design.md`). Escopo restante abaixo.
- [ ] 1.2 `whatbot/queue.py`: notificação de novo item na fila, listagem
      (`#fila`/comando equivalente) e resumo diário passam a indicar o
      **canal** de origem (`channel_label()`) ao lado do rótulo já existente
      (→ Requirement "Rótulo legível de contato", cenário "Fila mostra canal
      e identificador legível")

## 2. Testes

- [ ] 2.1 `tests/test_queue.py`: notificação de novo item mostra o canal ao
      lado do rótulo, para contato de WhatsApp e para um contato simulado de
      outro canal
- [ ] 2.2 Estender `test_handover_answers_customer_on_channel_and_admin_on_whatsapp`
      em `tests/test_main_e2e.py` para verificar que a notificação ao admin
      identifica o canal do cliente, não só que ela foi entregue no WhatsApp
- [ ] 2.3 Suíte completa verde
