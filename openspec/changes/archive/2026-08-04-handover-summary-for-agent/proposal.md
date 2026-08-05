# Resumo de interesse/estágio na notificação de handover

## Why

Hoje, quando um contato entra na fila, a notificação ao admin
(`whatbot/queue.py::process_new_handover`/`notify_admin`, mensagem montada
em `queue.py:168-174`) só traz nome, canal, prioridade e prazo de resposta.
`format_waiting_list` (`queue.py:49-91`), quando `include_last_message=True`,
anexa só um preview cru de até 120 caracteres da última mensagem
(`queue.py:81-85`). Não existe nenhuma síntese do que o cliente já
demonstrou interesse ou em que estágio da jornada ele está — o atendente
começa o atendimento sem esse contexto, mesmo quando ele já existe em
`SessionState`/`contatos.status` (`contact-interest-memory`).

Isso importa especialmente para pedidos do catálogo
(`catalog-order-capture`): um pedido Android completo e um pedido iOS sem
itens identificáveis disparam o mesmo handover automático, mas o atendente
precisa saber a diferença — no primeiro caso já sabe o que entregar/cobrar,
no segundo precisa perguntar ao cliente o que ele pediu antes de prosseguir.

## What Changes

- Nova função `whatbot/queue.py::build_contact_summary(contact,
  session_state, last_order=None) -> str`, reaproveitando
  `history_summary()` (`whatbot/session_state.py:75-92`) como base e
  somando: estágio atual (`contact.status`), item(ns) de interesse
  (`session.item_interesse`), e — quando o handover foi disparado por um
  pedido do catálogo — o conteúdo resolvido do pedido (nome/preço via
  `catalog-product-sync`, quando disponível) ou um aviso explícito quando
  `items_identifiable == False` ("pedido do catálogo — itens não
  identificados, confirmar com o cliente").
- `process_new_handover`/`notify_admin` (`queue.py:155-190`) passam a
  incluir esse resumo na mensagem de "Novo na fila", logo abaixo dos dados
  já existentes.
- `format_waiting_list` (`queue.py:49-91`) passa a usar
  `build_contact_summary` no lugar do preview cru de 120 caracteres quando
  `include_last_message=True`.

## Impact

- Specs afetadas: `admin` (mesma capability de `admin-bot-pause`)
- Código alterado: `whatbot/queue.py`
- Testes alterados: `tests/test_queue.py`
- Bloqueado por: `contact-interest-memory` (fonte do estágio/interesse a
  resumir); beneficia-se de `catalog-order-capture` e `catalog-product-sync`
  quando disponíveis, mas degrada graciosamente sem eles (resumo sem seção
  de pedido)
- Habilita: nenhum change adicional depende deste

## Fora de escopo (decisão explícita)

- Qualquer canal de notificação novo (email, dashboard web) — só o que já
  existe hoje (mensagem de WhatsApp para os admins via `send_admin`).
- Resumo gerado por LLM — `history_summary()` já é determinístico
  (baseado em palavras-chave), mantém esse padrão em vez de introduzir uma
  chamada de modelo só para formatar texto curto.
