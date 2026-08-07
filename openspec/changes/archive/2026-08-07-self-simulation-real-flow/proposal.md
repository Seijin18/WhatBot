# `#simular` como o próprio número do admin vira o fluxo real

## Why

O modo de teste do app da Meta (WhatsApp Cloud API) só aceita mensagens de
números explicitamente cadastrados — hoje, só o número do próprio admin
(`ADMIN_NOTIFY_PHONES`, que também é `DEFAULT_TEST_PHONE` nesta instalação).
Isso torna impossível testar o visualizador de conversas
(`conversation-history-media-storage`) e o botão "Assumir atendimento"
(`direct-human-takeover`) com um cliente de verdade: qualquer mensagem do
número do admin é sempre roteada para `is_admin_phone`, e `#simular` —
pensado para testar o bot sem tocar dados reais — explicitamente nunca
persiste em `mensagens` nem envia a resposta de volta pelo WhatsApp
("Simulação: resposta não enviada ao cliente fictício").

Mas quando o número simulado (`sim_phone`) é o **próprio** número do admin,
não há risco de corromper o histórico de um cliente real — é literalmente
a conversa real desse contato. Não faz sentido sandboxar esse caso
especificamente.

## What Changes

- `whatbot/main.py::run_admin_simulation`: quando `sim_phone` (após
  resolvido) é igual ao `admin_phone` normalizado, chama
  `process_customer_message(..., simulated=False, ...)` em vez de
  `simulated=True` — o turno passa a ser processado, persistido
  (`mensagens`, `session_state`) e respondido de verdade pelo canal, como
  qualquer conversa de cliente. Nesse caso, pula a decoração/reenvio
  "🧪 Teste como cliente" (evitaria duplicar a mensagem no mesmo número).
  Simular como **qualquer outro** número continua inteiramente sandboxed,
  sem nenhuma mudança de comportamento.
- Nenhuma mudança na interface nem na API administrativa: como
  `GET /admin/conversas`/`GET /admin/conversas/{id}/mensagens` já leem
  genericamente de `mensagens`/`contatos`, o histórico dessas conversas já
  aparece assim que existir — o gap era só a simulação nunca persistir
  nada para esse caso específico.

## Impact

- Specs afetadas: `admin` (estende)
- Código alterado: `whatbot/main.py` (`run_admin_simulation`)
- Testes alterados: `tests/test_main_e2e.py` (ou onde a simulação já é
  testada) — novo caso "simular como o próprio admin"
- Bloqueado por: nenhum
- Fora de escopo: qualquer mudança em como `#simular <outro-número>
  <mensagem>` funciona — continua idêntico, sandboxed.
