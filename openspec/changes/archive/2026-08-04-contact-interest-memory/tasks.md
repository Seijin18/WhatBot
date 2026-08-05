# Tasks — memória de interesse e estágio

## 1. Camada de dados

- [x] 1.1 `Database.set_contact_status(contact_id: int, status: str) ->
      None` — valida contra `{"novo_lead", "interessado", "comprando",
      "cliente_ativo", "cancelado"}`, levanta `ValueError` para qualquer
      outro valor (→ Requirement "Estágio do contato transiciona
      automaticamente")

## 2. Transição de estágio

- [x] 2.1 Função `whatbot/session_state.py::next_status(current_status,
      session, intent, has_order) -> str | None` — retorna o novo status
      quando há transição, `None` quando não há mudança; nunca regride
- [x] 2.2 `whatbot/main.py` chama `next_status` logo após
      `update_session_state` (`main.py:464`) e, se houver transição, chama
      `db.set_contact_status`
- [x] 2.3 Quando `catalog-order-capture` estiver disponível, um `order`
      presente no payload força `comprando` diretamente (sem depender de
      `INTENT_PEDIDO` textual) — `has_order` já existe no ponto de chamada
      (`whatbot/main.py`) fixado em `False` com um comentário explícito
      apontando para `payload.get("order") is not None` quando aquele change
      existir; `next_status` já trata `has_order=True` corretamente

## 3. Comando manual para `cliente_ativo`

- [x] 3.1 Nova intenção de admin (`mark_active_client`,
      `whatbot/admin_nlu.py` + `whatbot/admin.py::_resolve_mark_active_client`
      no mesmo padrão de `_resolve_reactivate` — `set_tipo_cliente`/
      `contact-segmentation-b2b-b2c` ainda não existem neste repo) para
      marcar um contato como `cliente_ativo` manualmente, reaproveitando
      resolução/desambiguação de `search_contacts_for_admin`

## 4. Testes

- [x] 4.1 `next_status`: `novo_lead` → `interessado` quando
      `item_interesse` deixa de estar vazio
- [x] 4.2 `next_status`: → `comprando` quando `intent == INTENT_PEDIDO` ou
      `has_order == True`
- [x] 4.3 `next_status` nunca regride (ex.: contato já `comprando` recebendo
      mensagem neutra permanece `comprando`)
- [x] 4.4 `set_contact_status` rejeita valor fora do conjunto fechado
- [x] 4.5 Comando manual de `cliente_ativo` funciona com desambiguação (mesmo
      padrão de `_resolve_reactivate`, já que `set_tipo_cliente` não existe
      neste repo)
- [x] 4.6 Suíte completa verde (`make test` / `pytest -q`) — 312 passed, 3
      skipped (pré-existentes, infra real)

`tests/test_main_e2e.py` (porta real `process_customer_message`/`main()`,
convenção de `openspec/project.md`) estendido com
`TestContactStatusTransitions`: transição `novo_lead`→`interessado`
persistida de fato no `FakeDatabase` (via `load_class_schedule_kb()`, já que
`knowledge/base.md` real não tem seção `## Itens`) e cobertura explícita do
guard `not simulated` (simulação não altera o status do contato real/
`sim_phone`-colidente).
