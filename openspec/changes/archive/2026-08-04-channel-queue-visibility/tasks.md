# Tasks — fila mostra canal e identificador legível

## 1. Implementação

- [x] ~~1.1 `whatbot/queue.py`: notificação de novo item na fila usa o
      rótulo legível do contato, em vez de `contact.phone` cru~~ — feito em
      `identity-multichannel` (ver `proposal.md`, Decisão 8 de
      `identity-multichannel/design.md`). Escopo restante abaixo.
- [x] 1.2 `whatbot/queue.py`: notificação de novo item na fila, listagem
      (`#fila`/comando equivalente) e resumo diário passam a indicar o
      **canal** de origem (`channel_label()`) ao lado do rótulo já existente
      (→ Requirement "Rótulo legível de contato", cenário "Fila mostra canal
      e identificador legível"). `build_daily_summary` não tinha nenhum
      rótulo por contato (só contadores agregados); para indicar canal sem
      mudar `db.py`/schema (fora do escopo — ver `proposal.md`, Impact), foi
      adicionada uma quebra por canal de "Ainda na fila" reaproveitando
      `db.get_waiting_contacts()`, já usado em outros pontos do módulo.

## 2. Testes

- [x] 2.1 `tests/test_queue.py`: notificação de novo item mostra o canal ao
      lado do rótulo, para contato de WhatsApp e para um contato simulado de
      outro canal
- [x] 2.2 Estender `test_handover_answers_customer_on_channel_and_admin_on_whatsapp`
      em `tests/test_main_e2e.py` para verificar que a notificação ao admin
      identifica o canal do cliente, não só que ela foi entregue no WhatsApp
- [x] 2.3 Suíte completa verde

## 3. Correções pós-revisão do critic (teste de mutação)

Um `critic` rodou teste de mutação (substituindo cada
`channel_label(contact.canal)` por um valor fixo) e achou 3 dos 4 pontos de
`whatbot/queue.py` sem nenhum teste que quebrasse com a mutação, além de dois
outros pontos da spec (`contact_resolver.py`, `admin.py`) sem canal exibido.

- [x] 3.1 `tests/test_queue.py`: `format_waiting_list` (a listagem `#fila`)
      tem teste de mutação para canal WhatsApp e Instagram
      (`TestQueueFormat.test_format_shows_whatsapp_channel_label` /
      `test_format_shows_instagram_channel_label`)
- [x] 3.2 `tests/test_queue.py`: `notify_assumption` tem teste de mutação
      para canal WhatsApp e Instagram (`TestNotifyAssumptionShowsChannel`)
- [x] 3.3 `tests/test_queue.py`: `build_daily_summary` tem teste de mutação
      para a quebra "Ainda na fila" por canal
      (`TestBuildDailySummaryShowsChannelBreakdown`)
- [x] 3.4 `whatbot/contact_resolver.py::format_disambiguation` e
      `whatbot/admin.py` (lista de candidatos do `reactivate`) passam a
      mostrar `channel_label()`, com teste de mutação
      (`test_admin_organic.py::TestContactResolver.test_disambiguation_shows_channel`
      e `TestReactivateDisambiguationShowsChannel`) — decisão registrada em
      `proposal.md` (Impact)
- [x] 3.5 Comentário impreciso em `whatbot/queue.py` (linha ~219, dizia "no
      new DB query") corrigido para refletir que `build_daily_summary` custa
      uma query extra por chamada
- [x] 3.6 Todas as 4 mutações confirmadas manualmente (não só a suíte
      normal): cada uma quebra o teste correspondente antes de reverter;
      suíte completa verde depois (159 testes, de 152 antes)
