# Design — memória de interesse e estágio

## Decisão 1: `status` continua `VARCHAR` livre, novos valores validados em Python

Mesmo padrão já estabelecido por `tipo_cliente`
(`contact-segmentation-b2b-b2c/design.md` Decisão 1) e já em uso por
`status`/`canal` neste projeto: sem `CHECK` constraint, sem enum de banco.
O conjunto fechado (`novo_lead`, `interessado`, `comprando`, `cliente_ativo`,
`cancelado`) é validado em `set_contact_status`, consistente com
`set_contact_tipo_cliente`.

## Decisão 2: estágio avança automaticamente, mas nunca regride nem confirma venda sozinho

Alternativas consideradas:

1. **Toda transição de estágio automática, incluindo `cliente_ativo`.**
   Rejeitada: confirmar que uma venda de fato aconteceu é uma decisão de
   negócio que depende de informação que o bot não tem certeza de possuir
   (pagamento confirmado, item enviado) — inferir isso automaticamente
   arrisca marcar como "cliente ativo" alguém que só demonstrou interesse
   forte. Mesma lógica de `contact-segmentation-b2b-b2c/design.md` Decisão 3
   (marcação manual para o que exige julgamento humano).
2. **Estágio automático até `comprando`, `cliente_ativo` só por ação manual
   do atendente (comando de admin, reaproveitando o padrão de
   `_resolve_reactivate`).** Escolhida.

Estágio nunca regride automaticamente (`interessado` não volta a
`novo_lead` se o cliente parar de responder) — reversão é decisão fora de
escopo deste change (ver `proposal.md`).

## Decisão 3: transição de estágio lê o mesmo `IntentResult`/`SessionState` já calculados

Para não reintroduzir o problema que `session-item-tracking-rename` corrige
(duas heurísticas paralelas divergindo), a lógica de transição de estágio
não roda uma nova análise de texto — ela olha para `session.item_interesse`
(já atualizado por `update_session_state`) e para `intent` (já roteado por
`route_intent`) no mesmo turno, no mesmo ponto de `main.py` onde os dois já
estão disponíveis (`main.py:464`).
