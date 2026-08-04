# Captura de pedidos do catálogo do WhatsApp

## Why

Quando um cliente monta um carrinho no catálogo do WhatsApp Business e toca
em "Enviar pedido", a Evolution API recebe esse evento como uma mensagem do
tipo `orderMessage` dentro do webhook `messages.upsert`. Hoje
`whatbot/webhook.py::_extract_text` não reconhece esse campo — só trata
`conversation`, `extendedTextMessage`, `imageMessage`, `videoMessage`,
`buttonsResponseMessage`, `listResponseMessage`. Como o texto extraído fica
vazio, `parse_evolution_payload` cai em `if not text: return None` e a
mensagem inteira é **descartada silenciosamente**: nenhum log, nenhuma
notificação, nenhum registro no histórico. O cliente pode ter certeza de que
o pedido foi recebido e ninguém do outro lado sabe que ele existe.

Investigação confirmou (issue [evolution-foundation/evolution-api#1819](https://github.com/evolution-foundation/evolution-api/issues/1819))
que o conteúdo desse `orderMessage` **não é confiável da mesma forma em
todas as plataformas**: pedidos originados de cliente Android trazem
`orderTitle` correto e dados suficientes para identificar os produtos;
pedidos originados de cliente iOS chegam sem lista de produtos, sem
`productId`/`retailerId`, e com `orderTitle` preenchido com o nome da
instância Evolution (não o do pedido) — não dá para saber o que foi pedido
só pelo webhook nesse caso. Qualquer tratamento de `orderMessage` precisa
assumir essa possibilidade, não é um caso raro hipotético.

## What Changes

- Nova função `whatbot/webhook.py::_extract_order(message: dict) -> dict |
  None`: reconhece `message.get("orderMessage")` e retorna um dict com o que
  houver disponível (`order_id`, `item_count`, `order_title`, lista de itens
  quando presente, e uma flag `items_identifiable: bool` — `False` quando
  não há `productId`/`retailerId` em nenhum item, cobrindo o caso iOS sem
  depender de detectar a plataforma diretamente).
- `_extract_text` passa a reconhecer `orderMessage` e produzir um texto
  sintético mínimo (nunca vazio) para que a mensagem nunca mais seja
  descartada por `if not text: return None` — ex.: `"[pedido do catálogo]
  {item_count} item(ns)"` quando identificável, `"[pedido do catálogo] itens
  não identificados"` quando não.
- `parse_evolution_payload` anexa o resultado de `_extract_order()` ao
  payload retornado (chave nova `order`, `None` quando a mensagem não é um
  pedido) — sem alterar o schema de `InboundMessage`
  (`whatbot/channels/base.py`), que já carrega o payload bruto em `raw`.
- `whatbot/priority.py`: um pedido do catálogo (`order` presente no payload)
  conta como prioridade 1 sempre, independente de `items_identifiable` —
  decisão de negócio confirmada: todo pedido real do catálogo dispara
  handover automático, porque mesmo quando os itens não são identificáveis
  (iOS) a IA não tem dado suficiente para conduzir a conversa sozinha.
- Handover automático disparado pelo mesmo mecanismo já usado por outros
  gatilhos em `whatbot/domain.py::executar_handover_para_secretaria`, sem
  criar um caminho de handover paralelo.

## Impact

- Specs afetadas: `catalog` (capability nova); `contacts` (satisfaz, não
  modifica, o requirement "Pedido de catálogo força estágio 'comprando'"
  já introduzido por `contact-interest-memory` — este change é quem liga
  `has_order` de fato, descoberto durante a revisão da implementação)
- Código alterado: `whatbot/webhook.py`, `whatbot/priority.py`,
  `whatbot/domain.py` (ponto de chamada do handover), `whatbot/main.py`
  (liga `order` a `next_status`/`db.set_contact_status`, guardado por
  `not simulated`)
- Testes alterados: suíte de `whatbot/webhook.py` (payloads Android/iOS
  sintéticos), `tests/test_main_e2e.py` (fluxo completo: pedido → handover
  → estágio `comprando`)
- Bloqueado por: nenhum
- Habilita (não bloqueia): `catalog-product-sync` (resolve nome/preço dos
  itens capturados aqui), `handover-summary-for-agent` (usa o `order`
  capturado aqui para montar o resumo do handover)

## Fora de escopo (decisão explícita)

- Resolver `productId`/`retailerId` para nome e preço do produto — depende
  de uma fonte de catálogo local, que é o `catalog-product-sync`. Este
  change só captura e preserva o que o webhook trouxe.
- Confirmar com o cliente os itens de um pedido iOS sem dados — fica a
  cargo do atendente humano depois do handover automático, não é um fluxo
  conversacional automatizado nesta fase.
- Migrar para a WhatsApp Cloud API oficial da Meta (eliminaria a
  inconsistência Android/iOS na origem) — ver nota em
  `catalog-product-sync/design.md`; não é avaliado aqui.
