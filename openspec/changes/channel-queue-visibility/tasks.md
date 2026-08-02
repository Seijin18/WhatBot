# Tasks — fila mostra canal e identificador legível

## 1. Implementação

- [ ] 1.1 `whatbot/queue.py`: notificação de novo item na fila usa
      `channel_label()` e o rótulo legível do contato, em vez de
      `contact.phone` cru
      (→ Requirement "Rótulo legível de contato", cenário "Fila mostra canal
      e identificador legível")
- [ ] 1.2 Listagem da fila (`#fila` / comando equivalente) e resumo diário
      seguem o mesmo padrão
      (→ idem)

## 2. Testes

- [ ] 2.1 `tests/test_queue.py`: notificação de novo item mostra canal e
      rótulo, para contato de WhatsApp e para um contato simulado de outro
      canal
- [ ] 2.2 Estender `test_handover_answers_customer_on_channel_and_admin_on_whatsapp`
      em `tests/test_main_e2e.py` para verificar que a notificação ao admin
      identifica o canal do cliente, não só que ela foi entregue no WhatsApp
- [ ] 2.3 Suíte completa verde
