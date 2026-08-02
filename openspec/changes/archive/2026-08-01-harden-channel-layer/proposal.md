# Endurecer a camada de canais antes da migração de identidade

## Why

A Fase 1 do `docs/INSTAGRAM_INTEGRATION_PLAN.md` foi entregue: `whatbot/channels/`
existe e todo envio passa pelo `ChannelRouter`. Os critérios de aceite estáticos
da fase passam — a suíte roda sem alteração de asserções e não há mais nenhuma
chamada direta ao cliente concreto em `main`, `domain` ou `queue`.

O problema é o que a suíte verde **não** cobre:

- Nenhum teste percorre `webhook → main() → router → send`. Os únicos testes que
  chamam `main()` mockam `_init_infra` **e** `process_customer_message` — ou seja,
  mockam exatamente o código que a Fase 1 alterou.
- `EvolutionApiClient` foi movido de módulo e ganhou um kwarg novo sem que exista
  um único teste sobre ele.
- Não existe fake de `Database`, e `whatbot/db.py` exige Postgres real. Por isso
  `process_customer_message`, `executar_handover_para_secretaria`,
  `handle_admin_message` e todas as funções de `queue.py` são inalcançáveis por
  teste — o rename `whatsapp` → `router` nesses quatro módulos tem cobertura zero.

A Fase 2 reescreve `db.py` inteiro, trocando a chave de identidade de `phone`
para `(canal, external_id)`. O plano elege "a suíte atual passa sem mudança de
asserção" como portão de regressão, mas esse portão está oco justamente na camada
que a Fase 2 vai reescrever. Construir a rede de segurança agora é pré-requisito.

A auditoria também encontrou sete defeitos latentes na camada nova. Nenhum quebra
o WhatsApp hoje — em produção o roteador registra só o cliente WhatsApp e
`UnknownChannelError` é um modo de falha correto — mas todos detonam quando o
Instagram entrar, quando depurar custa muito mais caro.

## What Changes

- **Harness de teste:** `tests/fakes.py` com um `FakeDatabase` em memória cobrindo
  a superfície pública de `Database`, mais os fakes de cliente de canal que hoje
  vivem dentro de `tests/test_channel_router.py`.
- **Testes E2E** na costura do `main()`, exercitando o rename inteiro: resposta
  do bot, handover, comando de admin, resposta da staff pelo WhatsApp Business,
  LLM indisponível, e o invariante "cliente no canal dele, admin no WhatsApp".
- **Testes do `EvolutionApiClient`** com `requests` mockado.
- **Correção de sete defeitos** da camada de canais (detalhados em `design.md`):
  propagação de canal na simulação de admin, validação de canal na borda,
  alinhamento do cliente ao protocolo, adoção da taxonomia de erro tipada,
  simetria dos helpers de despacho, uso real do `InboundMessage`, e limpeza.

Nenhuma mudança de comportamento no WhatsApp. Nenhuma asserção de teste existente
é alterada.

## Impact

- Specs afetadas: `channels`
- Código: `whatbot/channels/` (`base.py`, `router.py`, `whatsapp_evolution.py`),
  `whatbot/main.py`, `whatbot/webhook.py`
- Testes: novos `tests/fakes.py`, `tests/test_main_e2e.py`,
  `tests/test_evolution_client.py`; `tests/test_channel_router.py` passa a
  importar os fakes de `tests/fakes.py` sem alterar asserções
- Desbloqueia: Fase 2 (migração de identidade para `(canal, external_id)`)
