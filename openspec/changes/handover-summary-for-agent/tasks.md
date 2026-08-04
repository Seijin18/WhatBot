# Tasks — resumo de interesse/estágio na notificação de handover

## 1. Construção do resumo

- [ ] 1.1 `whatbot/queue.py::build_contact_summary(contact, session_state,
      last_order=None) -> str` — estágio + `item_interesse` +
      `history_summary()` (→ Requirement "Notificação de handover inclui
      resumo do contato")
- [ ] 1.2 Seção de pedido: quando `last_order` presente e
      `items_identifiable`, lista nome/preço resolvidos (via
      `catalog-product-sync`, se disponível) ou o bruto capturado por
      `catalog-order-capture`; quando não identificável, texto fixo
      avisando o atendente

## 2. Integração com as notificações existentes

- [ ] 2.1 `process_new_handover`/`notify_admin` (`queue.py:155-190`)
      incluem `build_contact_summary` na mensagem de "Novo na fila"
- [ ] 2.2 `format_waiting_list` (`queue.py:49-91`) usa
      `build_contact_summary` no lugar do preview cru quando
      `include_last_message=True`

## 3. Testes

- [ ] 3.1 Resumo sem interesse registrado é curto/vazio, sem quebrar
      formatação da notificação
- [ ] 3.2 Resumo com item de interesse e estágio `interessado` aparece
      corretamente formatado
- [ ] 3.3 Resumo de pedido identificável (Android) lista os itens
- [ ] 3.4 Resumo de pedido não identificável (iOS) mostra o aviso explícito
      para o atendente
- [ ] 3.5 `format_waiting_list` com `include_last_message=True` usa o novo
      resumo, sem regressão no formato da lista
- [ ] 3.6 Suíte completa verde (`make test` / `pytest -q`)
