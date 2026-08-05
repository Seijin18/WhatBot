# Sincronização local do catálogo de produtos

## Why

Nem um pedido completo do catálogo (`catalog-order-capture`, caso Android)
nem uma pergunta livre do cliente sobre um produto ("vocês têm a miniatura
X?") dão ao bot um nome ou preço legível — o `orderMessage` só carrega
`productId`/`retailerId` opacos, e hoje não existe nenhuma fonte de
catálogo estruturada no projeto (`knowledge/` é texto livre para a LLM, não
uma lista de produtos com id). Sem resolver isso, o bot não consegue "falar
sobre os itens" nem enriquecer a notificação de handover de um pedido com o
que foi pedido de fato.

A Evolution API (self-hosted, Baileys) expõe `POST
{base_url}/chat/fetchCatalogs` e `POST {base_url}/chat/fetchCollections`
desde a versão 2.3.0 (17/06/2025) — o `docker-compose.yml` deste projeto já
roda `evoapicloud/evolution-api:v2.3.7`, posterior a essa versão. Isso
resolve o problema **sem precisar da WhatsApp Cloud API oficial da Meta**
(ver "Fora de escopo" abaixo).

## What Changes

- Novo método `EvolutionApiClient.fetch_catalog() -> list[dict]`
  (`whatbot/channels/whatsapp_evolution.py`, mesmo padrão de `send_text`:
  header `apikey`, `base_url`/`instance_name` já configurados), chamando
  `POST /chat/fetchCatalogs`.
- Nova tabela `produtos_catalogo` em `ensure_schema()` (`whatbot/db.py`,
  mesmo padrão idempotente das demais tabelas): `product_id` (chave,
  correspondente ao `productId`/`retailerId` do `orderMessage`), `nome`,
  `preco`, `disponivel`, `last_synced_at`.
- Job de sincronização (mesmo padrão de agendamento de
  `windmill/f/whatbot/check_queue.py`) que chama `fetch_catalog()`
  periodicamente e faz upsert em `produtos_catalogo`.
- `Database.resolve_catalog_items(product_ids: list[str]) -> list[dict]` —
  resolve uma lista de `productId` para nome/preço, usada por
  `catalog-order-capture` (enriquecer pedidos) e por
  `handover-summary-for-agent` (montar o resumo).

## Impact

- Specs afetadas: `catalog` (estende a capability criada em
  `catalog-order-capture`)
- Código alterado: `whatbot/channels/whatsapp_evolution.py`, `whatbot/db.py`,
  novo job em `windmill/f/whatbot/`
- Testes alterados: suíte de `whatbot/channels/whatsapp_evolution.py`
  (fake HTTP), suíte de `whatbot/db.py` (upsert idempotente)
- Bloqueado por: nenhum (independente de `catalog-order-capture`)
- Habilita: `catalog-order-capture` (resolução de itens de pedido),
  `contact-interest-memory` (nomes reais de produto na memória de
  interesse), `handover-summary-for-agent` (resumo com nome/preço)

## Fora de escopo (decisão explícita — melhoria futura)

- **Migrar para a WhatsApp Cloud API oficial da Meta para leitura do
  catálogo.** Eliminaria de vez a dependência de `/chat/fetchCatalogs` (não
  documentado oficialmente pela Meta, é uma engenharia reversa da Evolution
  API sobre o protocolo do WhatsApp Web) e teria uma API estável e mantida
  pela própria Meta. Mas exige: conta comercial verificada no WhatsApp
  Business Manager, app aprovado pela Meta com permissão de catálogo, e
  reescrever `whatbot/channels/whatsapp_evolution.py` inteiro (autenticação
  por token da Meta, não `apikey` de instância self-hosted) — é
  efetivamente trocar a integração de canal, não uma extensão aditiva. Só
  faz sentido avaliar isso se a operação decidir migrar de Evolution API
  para Cloud API por outros motivos também (ex.: estabilidade de conexão,
  suporte oficial); não é escopo deste change nem dos changes vizinhos.
- Interface de administração para editar produtos manualmente — a fonte de
  verdade continua sendo o catálogo real do WhatsApp Business, sincronizado,
  não um cadastro paralelo.
