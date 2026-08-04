# Tasks — memória de interesse e estágio

## 1. Camada de dados

- [ ] 1.1 `Database.set_contact_status(contact_id: int, status: str) ->
      None` — valida contra `{"novo_lead", "interessado", "comprando",
      "cliente_ativo", "cancelado"}`, levanta `ValueError` para qualquer
      outro valor (→ Requirement "Estágio do contato transiciona
      automaticamente")

## 2. Transição de estágio

- [ ] 2.1 Função `whatbot/session_state.py::next_status(current_status,
      session, intent, has_order) -> str | None` — retorna o novo status
      quando há transição, `None` quando não há mudança; nunca regride
- [ ] 2.2 `whatbot/main.py` chama `next_status` logo após
      `update_session_state` (`main.py:464`) e, se houver transição, chama
      `db.set_contact_status`
- [ ] 2.3 Quando `catalog-order-capture` estiver disponível, um `order`
      presente no payload força `comprando` diretamente (sem depender de
      `INTENT_PEDIDO` textual)

## 3. Comando manual para `cliente_ativo`

- [ ] 3.1 Nova intenção de admin (mesmo padrão de `set_tipo_cliente` em
      `contact-segmentation-b2b-b2c`) para marcar um contato como
      `cliente_ativo` manualmente, reaproveitando resolução/desambiguação de
      `search_contacts_for_admin`

## 4. Testes

- [ ] 4.1 `next_status`: `novo_lead` → `interessado` quando
      `item_interesse` deixa de estar vazio
- [ ] 4.2 `next_status`: → `comprando` quando `intent == INTENT_PEDIDO` ou
      `has_order == True`
- [ ] 4.3 `next_status` nunca regride (ex.: contato já `comprando` recebendo
      mensagem neutra permanece `comprando`)
- [ ] 4.4 `set_contact_status` rejeita valor fora do conjunto fechado
- [ ] 4.5 Comando manual de `cliente_ativo` funciona com desambiguação igual
      a `set_tipo_cliente`
- [ ] 4.6 Suíte completa verde (`make test` / `pytest -q`)
