# Tasks — captura de pedidos do catálogo

## 1. Extração do payload

- [ ] 1.1 `whatbot/webhook.py::_extract_order(message: dict) -> dict | None`
      — reconhece `message.get("orderMessage")`, retorna `order_id`,
      `item_count`, `order_title`, `items` (lista bruta, pode ser vazia) e
      `items_identifiable` (→ Requirement "Pedido do catálogo nunca é
      descartado")
- [ ] 1.2 `_extract_text` reconhece `orderMessage` e retorna texto sintético
      não-vazio (identificável vs. não identificável)
- [ ] 1.3 `parse_evolution_payload` anexa `order = _extract_order(...)` ao
      dict retornado

## 2. Priorização e handover

- [ ] 2.1 `whatbot/priority.py`: payload com `order` presente força
      prioridade 1, sem checar `items_identifiable`
- [ ] 2.2 Fluxo de processamento (`whatbot/main.py`/`whatbot/domain.py`)
      dispara `executar_handover_para_secretaria` sempre que `order` estiver
      presente, reaproveitando o mecanismo de handover existente (não criar
      caminho paralelo)

## 3. Testes

- [ ] 3.1 Payload sintético Android (`orderMessage` completo, `productId`
      presente em todos os itens) → `order.items_identifiable == True`,
      handover disparado, prioridade 1
- [ ] 3.2 Payload sintético iOS (`orderMessage` sem `productId`/`retailerId`,
      `orderTitle` = nome de instância) → `order.items_identifiable ==
      False`, handover disparado do mesmo jeito, texto sintético indica
      "itens não identificados"
- [ ] 3.3 Mensagem sem `orderMessage` continua funcionando exatamente como
      hoje (`order is None`, nenhuma regressão nos outros tipos de mensagem
      de `_extract_text`)
- [ ] 3.4 `tests/test_main_e2e.py` estendido: pedido do catálogo → contato
      entra na fila de handover
- [ ] 3.5 Suíte completa verde (`make test` / `pytest -q`)
