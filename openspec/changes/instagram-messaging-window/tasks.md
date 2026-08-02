# Tasks — janela de mensageria do Instagram

## 1. Persistência

- [x] 1.1 Persistir `last_inbound_at` a cada mensagem de entrada do Instagram
      (→ Requirement "Janela de mensageria de 24 horas"). Guardado por
      `not simulated`: `run_admin_simulation` nunca deve gravar
      `last_inbound_at` do contato real (critic Bloqueador 3). Coberto por
      `tests/test_main_e2e.py::TestLastInboundAtIsPersisted` e
      `TestAdminSimulationDoesNotTouchLastInboundAt`.

## 2. Regra de negócio

- [x] 2.1 Verificação da janela dentro de `whatbot/channels/instagram.py`
      (método `send_text`, ver `design.md`), com relógio injetável, antes
      de despachar qualquer envio: dentro de 24h envia normal, entre 24h e
      7 dias exige `human_agent=True`, fora de 7 dias levanta
      `ChannelError(cause="window_expired")`
      (→ Requirement "Janela de mensageria de 24 horas", cenários "dentro da
      janela" / "fora da janela" / "atendimento humano fora de 24h" / "fora
      de 7 dias")
      Fail-closed (critic Bloqueador 1): sem `last_inbound_lookup` injetado,
      `send_text` bloqueia com `cause=CAUSE_WINDOW_CHECK_UNAVAILABLE` em vez
      de despachar sem checagem. Ver `instagram_last_inbound_lookup(db)` em
      `whatbot/channels/instagram.py` — helper que fixa `canal=INSTAGRAM` na
      injeção, porque `Database.get_last_inbound_at` agora exige `canal`
      explícito (critic Importante 5).
- [x] 2.2 Reativação automática do bot não gera mensagem proativa
      (→ Requirement "Janela de mensageria de 24 horas", cenário "Reativação
      automática não é proativa")
- [x] 2.3 Notificação de fila (`whatbot/queue.py`, já estendida por
      `channel-queue-visibility`) informa prazo de resposta quando o canal
      impõe janela (→ Requirement "Notificação de fila informa prazo de
      resposta"). Cobre tanto `process_new_handover` quanto
      `format_waiting_list` (notificação de lote, espera prolongada e o
      comando "quem está na fila?") — critic Importante 4.

## 3. Testes

- [x] 3.1 `tests/test_messaging_window.py`: os quatro cenários de janela,
      com relógio injetado
- [x] 3.2 Teste de reativação sem mensagem proativa
- [x] 3.3 Caso em `tests/test_main_e2e.py`: mensagem automática bloqueada
      fora da janela, sem erro exposto ao cliente
- [x] 3.4 Suíte completa verde
- [x] 3.5 Correções de revisão do critic (teste de mutação): fail-closed sem
      `last_inbound_lookup` (Bloqueador 1), persistência de `last_inbound_at`
      coberta por teste (Bloqueador 2), simulação de admin não corrompe
      `last_inbound_at` real (Bloqueador 3), `format_waiting_list` mostra
      prazo (Importante 4), `get_last_inbound_at` exige `canal` explícito +
      helper `instagram_last_inbound_lookup` (Importante 5). Mutação
      verificada manualmente para os 3 bloqueadores (revert → teste falha →
      reaplica).
