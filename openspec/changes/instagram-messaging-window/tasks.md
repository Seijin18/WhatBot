# Tasks — janela de mensageria do Instagram

## 1. Persistência

- [ ] 1.1 Persistir `last_inbound_at` a cada mensagem de entrada do Instagram
      (→ Requirement "Janela de mensageria de 24 horas")

## 2. Regra de negócio

- [ ] 2.1 Verificação da janela dentro de `whatbot/channels/instagram.py`
      (método `send_text`, ver `design.md`), com relógio injetável, antes
      de despachar qualquer envio: dentro de 24h envia normal, entre 24h e
      7 dias exige `human_agent=True`, fora de 7 dias levanta
      `ChannelError(cause="window_expired")`
      (→ Requirement "Janela de mensageria de 24 horas", cenários "dentro da
      janela" / "fora da janela" / "atendimento humano fora de 24h" / "fora
      de 7 dias")
- [ ] 2.2 Reativação automática do bot não gera mensagem proativa
      (→ Requirement "Janela de mensageria de 24 horas", cenário "Reativação
      automática não é proativa")
- [ ] 2.3 Notificação de fila (`whatbot/queue.py`, já estendida por
      `channel-queue-visibility`) informa prazo de resposta quando o canal
      impõe janela (→ Requirement "Notificação de fila informa prazo de
      resposta")

## 3. Testes

- [ ] 3.1 `tests/test_messaging_window.py`: os quatro cenários de janela,
      com relógio injetado
- [ ] 3.2 Teste de reativação sem mensagem proativa
- [ ] 3.3 Caso em `tests/test_main_e2e.py`: mensagem automática bloqueada
      fora da janela, sem erro exposto ao cliente
- [ ] 3.4 Suíte completa verde
