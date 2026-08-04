# Tasks — sincronização local do catálogo

## 1. Cliente Evolution API

- [ ] 1.1 `EvolutionApiClient.fetch_catalog() -> list[dict]`
      (`whatbot/channels/whatsapp_evolution.py`), `POST
      /chat/fetchCatalogs`, mesmo tratamento de erro/log de
      `send_text` (→ Requirement "Catálogo sincronizado periodicamente")

## 2. Schema e persistência

- [ ] 2.1 `CREATE TABLE IF NOT EXISTS produtos_catalogo (product_id
      VARCHAR(64) PRIMARY KEY, nome TEXT, preco NUMERIC, disponivel BOOLEAN,
      last_synced_at TIMESTAMPTZ)` em `ensure_schema()`
- [ ] 2.2 `Database.upsert_catalog_products(products: list[dict]) -> None`
      — upsert por `product_id`
- [ ] 2.3 `Database.resolve_catalog_items(product_ids: list[str]) ->
      list[dict]` — `SELECT ... WHERE product_id = ANY(%s)`

## 3. Job de sincronização

- [ ] 3.1 Novo job (mesmo padrão de `windmill/f/whatbot/check_queue.py`)
      chamando `fetch_catalog()` + `upsert_catalog_products()`
- [ ] 3.2 Log/alerta quando a sincronização falha (não deve derrubar o job,
      só deixar o cache desatualizado — próxima execução tenta de novo)

## 4. Testes

- [ ] 4.1 `fetch_catalog()` contra fake HTTP: sucesso e falha de rede
- [ ] 4.2 Upsert idempotente: rodar duas vezes com o mesmo catálogo não
      duplica linhas, atualiza `last_synced_at`
- [ ] 4.3 `resolve_catalog_items` com ids desconhecidos retorna lista
      parcial (não levanta erro para id que não está no cache)
- [ ] 4.4 Suíte completa verde (`make test` / `pytest -q`)
