# Tasks — resumo de interesse/estágio na notificação de handover

## 1. Construção do resumo

- [x] 1.1 `whatbot/queue.py::build_contact_summary(contact, session_state,
      last_order=None) -> str` — estágio + `item_interesse` +
      `history_summary()` (→ Requirement "Notificação de handover inclui
      resumo do contato"). Aceita ainda um `history` opcional
      (`List[MessageRecord]`) — decisão de implementação: `history_summary()`
      precisa do histórico de mensagens, que não estava no escopo do
      `contact`/`session_state` recebidos; buscá-lo é responsabilidade do
      chamador (`db.get_recent_messages`), mantendo `build_contact_summary`
      livre de `Database` (mesmo espírito da Decisão 2 para `last_order`).
      `WaitingContact` ganhou os campos aditivos `status`/`session_state`
      (`whatbot/db.py`, `_waiting_select`/`_row_to_waiting`, espelhado em
      `tests/fakes.py`) para que essa informação chegue até o ponto de
      montagem do resumo.
- [x] 1.2 Seção de pedido: quando `last_order` presente e
      `items_identifiable`, lista nome/preço resolvidos (via
      `catalog-product-sync`, se disponível) ou o bruto capturado por
      `catalog-order-capture`; quando não identificável, texto fixo
      avisando o atendente. A resolução via `Database.resolve_catalog_items`
      acontece no chamador (`process_new_handover`, via
      `_resolve_order_for_summary`), que enriquece `last_order` com uma
      chave `resolved_items` antes de chamar `build_contact_summary` —
      mantém a função sem depender de `Database` (Decisão 2).
      Revisão do critic (resolução parcial e quantidade): quando o cache
      resolve só PARTE dos `productId` de um pedido, `_format_order_summary`
      lista os itens conhecidos e sinaliza explicitamente
      `"+ N item(ns) não identificado(s)"` (nunca mostra um pedido mais
      curto que o real sem avisar) — só cai para o bruto quando NADA foi
      resolvido. `_resolve_order_for_summary` também mescla `quantity` de
      `order["items"]` de volta em cada `resolved_items` (perdida antes,
      pois `Database.resolve_catalog_items` só devolve
      nome/preço/disponibilidade), e `_format_resolved_order_item` exibe
      `"Boné x3 (R$ 29,90 cada)"` em vez de tratar 3 unidades como 1.
      Preço também passou a formatação pt-BR (`R$ 29,90`, não `R$ 29.9`).

## 2. Integração com as notificações existentes

- [x] 2.1 `process_new_handover`/`notify_admin` (`queue.py:155-190`)
      incluem `build_contact_summary` na mensagem de "Novo na fila".
      `process_new_handover` ganhou o parâmetro `last_order`, encadeado
      desde `executar_handover_para_secretaria` (`whatbot/domain.py`).
- [x] 2.2 `format_waiting_list` (`queue.py:49-91`) usa
      `build_contact_summary` no lugar do preview cru quando
      `include_last_message=True`

## 3. Testes

- [x] 3.1 Resumo sem interesse registrado é curto/vazio, sem quebrar
      formatação da notificação
- [x] 3.2 Resumo com item de interesse e estágio `interessado` aparece
      corretamente formatado
- [x] 3.3 Resumo de pedido identificável (Android) lista os itens
- [x] 3.4 Resumo de pedido não identificável (iOS) mostra o aviso explícito
      para o atendente
- [x] 3.5 `format_waiting_list` com `include_last_message=True` usa o novo
      resumo, sem regressão no formato da lista
- [x] 3.6 Suíte completa verde (`make test` / `pytest -q`) — estendido
      também `tests/test_main_e2e.py::TestCatalogOrderCapture` com dois
      testes ponta a ponta (pedido Android resolvido via
      `catalog-product-sync`, pedido iOS com aviso explícito) já que este
      change toca o ciclo de handover ali coberto.
