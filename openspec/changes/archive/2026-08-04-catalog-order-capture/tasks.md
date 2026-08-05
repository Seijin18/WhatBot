# Tasks — captura de pedidos do catálogo

## 1. Extração do payload

- [x] 1.1 `whatbot/webhook.py::_extract_order(message: dict) -> dict | None`
      — reconhece `message.get("orderMessage")`, retorna `order_id`,
      `item_count`, `order_title`, `items` (lista bruta, pode ser vazia) e
      `items_identifiable` (→ Requirement "Pedido do catálogo nunca é
      descartado")
- [x] 1.2 `_extract_text` reconhece `orderMessage` e retorna texto sintético
      não-vazio (identificável vs. não identificável)
- [x] 1.3 `parse_evolution_payload` anexa `order = _extract_order(...)` ao
      dict retornado

## 2. Priorização e handover

- [x] 2.1 `whatbot/priority.py`: payload com `order` presente força
      prioridade 1, sem checar `items_identifiable`
- [x] 2.2 Fluxo de processamento (`whatbot/main.py`/`whatbot/domain.py`)
      dispara `executar_handover_para_secretaria` sempre que `order` estiver
      presente, reaproveitando o mecanismo de handover existente (não criar
      caminho paralelo)
- [x] 2.3 `whatbot/main.py`: `order` presente também satisfaz o requirement
      já em vigor `openspec/specs/contacts/spec.md` ("Estágio do contato
      transiciona automaticamente" → "Pedido de catálogo força estágio
      'comprando'", introduzido por `contact-interest-memory`) — chama
      `next_status(..., has_order=True)`/`db.set_contact_status` no mesmo
      branch do handover, respeitando o guard `not simulated`. Achado pelo
      critic na 1ª rodada de revisão (bloqueador), corrigido na 2ª.

## 3. Testes

- [x] 3.1 Payload sintético Android (`orderMessage` completo, `productId`
      presente em todos os itens) → `order.items_identifiable == True`,
      handover disparado, prioridade 1
- [x] 3.2 Payload sintético iOS (`orderMessage` sem `productId`/`retailerId`,
      `orderTitle` = nome de instância) → `order.items_identifiable ==
      False`, handover disparado do mesmo jeito, texto sintético indica
      "itens não identificados"
- [x] 3.3 Mensagem sem `orderMessage` continua funcionando exatamente como
      hoje (`order is None`, nenhuma regressão nos outros tipos de mensagem
      de `_extract_text`)
- [x] 3.4 `tests/test_main_e2e.py` estendido: pedido do catálogo → contato
      entra na fila de handover; também cobre `contact.status == "comprando"`
      (Android e iOS, a partir de `novo_lead` e `interessado`) e o guard
      `not simulated` (→ tarefa 2.3)
- [x] 3.5 Suíte completa verde (`make test` / `pytest -q`) — 340 testes, 0
      falhas
- [x] 3.6 Edge case `orderMessage: {}` (dict vazio) não recai no descarte
      silencioso original; `_extract_order` deixou de ser chamado duas
      vezes por payload em `parse_evolution_payload` (achados menores do
      critic)
