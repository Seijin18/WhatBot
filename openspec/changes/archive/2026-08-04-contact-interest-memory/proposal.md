# Memória de interesse e estágio do cliente

## Why

`SessionState` (`whatbot/session_state.py`) já rastreia interesse
(`modalidade_interesse`/`item_interesse` após `session-item-tracking-rename`)
e tópico atual por contato, persistido na coluna `contatos.session_state`
(JSONB, já existe — `whatbot/db.py:146`, `Database.update_contact_session_state`
já grava). O que falta:

- `contatos.status` (`novo_lead`/`cliente_ativo`/`cancelado`,
  `whatbot/config.py:11-32`) é escrito **uma única vez** na criação do
  contato (`db.py:290`, default `"novo_lead"`) e nunca mais transiciona —
  não existe hoje nenhum sinal de "virou lead quente"/"está comprando"/
  "virou cliente". O commit `2987b1b` já registrou `cliente_ativo` como
  "confirmado sem uso vivo".
- Interesse em produto e pedidos concretos do catálogo
  (`catalog-order-capture`) vivem em lugares separados, sem se somarem num
  estágio único e legível.

## Dependência

Este change assume `session-item-tracking-rename` (proposto separadamente,
`openspec/changes/session-item-tracking-rename/`) já aplicado — vocabulário
neutro (`item_interesse`, não `modalidade_interesse`) e rastreio de
interesse vindo de `IntentResult.items` (já calculado por `route_intent`),
não de uma heurística de texto paralela. Não duplica esse trabalho: parte
dele.

## What Changes

- `SessionState` ganha um campo de estágio derivado (não persiste redundante
  com `contatos.status` — lê/escreve através dele): quando `item_interesse`
  deixa de estar vazio, e ainda não há pedido nem handover, o estágio avança
  de `novo_lead` para `interessado`; quando um pedido do catálogo chega
  (`catalog-order-capture`, se disponível) ou o cliente confirma intenção de
  compra em texto (`INTENT_PEDIDO`), avança para `comprando`; a confirmação
  de venda/cadastro continua sendo uma ação manual do atendente (mesma
  filosofia de `contact-segmentation-b2b-b2c/design.md` Decisão 3: marcação
  manual, não inferência automática, para o estado final).
- Novo método `Database.set_contact_status(contact_id: int, status: str) ->
  None`, validando contra um conjunto fechado (mesmo padrão de
  `set_contact_tipo_cliente`: `VARCHAR` livre validado em Python, não enum
  de banco).
- Transição de estágio chamada a partir do mesmo ponto em `whatbot/main.py`
  que já chama `update_session_state` (`main.py:464`) — sem novo ponto de
  entrada no pipeline.
- Quando `catalog-product-sync` estiver disponível, o interesse registrado
  usa nome real de produto (via `resolve_catalog_items`); sem ele, continua
  funcionando só com o texto livre resolvido por `item_interesse` — sem
  dependência bloqueante.

## Impact

- Specs afetadas: `conversa` (extensão de `SessionState`), `contacts`
  (transição de `status`, capability já existente desde
  `contact-segmentation-b2b-b2c`)
- Código alterado: `whatbot/session_state.py`, `whatbot/db.py`,
  `whatbot/main.py`
- Testes alterados: suíte de `whatbot/session_state.py`, suíte de
  `whatbot/db.py`, `tests/test_main_e2e.py`
- Bloqueado por: `session-item-tracking-rename` (vocabulário e fonte de
  interesse)
- Habilita: `handover-summary-for-agent`

## Fora de escopo (decisão explícita)

- Prompt de sistema diferente por estágio granular (`interessado`/
  `comprando`) — `SYSTEM_PROMPTS` continua indexado só pelos três valores
  originais; `build_system_prompt_for_status` já cai em `novo_lead` para
  qualquer status desconhecido (`main.py:157-158`), então os novos estágios
  não quebram nada, só não têm prompt dedicado ainda. Mesma decisão já
  tomada em `contact-segmentation-b2b-b2c/proposal.md` para `tipo_cliente`,
  pelo mesmo motivo.
- Reversão automática de estágio (ex.: `comprando` → `interessado` se o
  cliente sumir) — não avaliado nesta fase.
