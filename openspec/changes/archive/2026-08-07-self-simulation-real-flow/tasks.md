# Tasks — `#simular` como o próprio admin vira fluxo real

## 1. `whatbot/main.py`

- [x] 1.1 `run_admin_simulation`: detectar `is_self_simulation = canal ==
      WHATSAPP and sim_phone == admin_phone` (ambos já normalizados)
      (→ Requirement "Simular como o próprio admin usa o fluxo real")
- [x] 1.2 Quando `is_self_simulation`: chamar `process_customer_message`
      com `simulated=False`, `push_name` real (não "Simulado por ..."),
      `history_override`/`session_override` forçados a `None` (usa o
      estado real do contato, não o shadow da sessão de simulação)
- [x] 1.3 Quando `is_self_simulation`: retornar direto após
      `process_customer_message`, sem a decoração/reenvio "🧪 Teste como
      cliente" (já foi enviado de verdade dentro do fluxo real)
- [x] 1.4 Simular como qualquer outro número (`sim_phone != admin_phone`):
      comportamento idêntico ao atual, nenhuma regressão

## 2. Testes

- [x] 2.1 `#simular <próprio número admin> <mensagem>` (ou sessão
      persistente `#simular` com número coincidindo): mensagem persiste em
      `mensagens`, resposta do bot é enviada de verdade pelo router
- [x] 2.2 `#simular <outro número> <mensagem>`: continua não persistindo
      nada, resposta só decorada e enviada ao admin (comportamento atual,
      teste de regressão)
- [x] 2.3 Suíte completa verde
