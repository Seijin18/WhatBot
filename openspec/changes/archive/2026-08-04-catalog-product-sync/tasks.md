# Tasks — sincronização local do catálogo

## 1. Cliente Evolution API

- [x] 1.1 `EvolutionApiClient.fetch_catalog() -> list[dict]`
      (`whatbot/channels/whatsapp_evolution.py`), `POST
      /chat/fetchCatalogs`, mesmo tratamento de erro/log de
      `send_text` (→ Requirement "Catálogo sincronizado periodicamente")
      — **nota (assunção não validada):** o campo `preco` é copiado do
      `price` bruto da API sem conversão de escala; não há confirmação, sem
      uma instância real da Evolution API para inspecionar, de que `price`
      venha em unidade decimal (ex.: 49.90) em vez de centavos (ex.: 4990).
      Revisar `EvolutionApiClient._to_catalog_product` assim que o job rodar
      contra um catálogo real.

## 2. Schema e persistência

- [x] 2.1 `CREATE TABLE IF NOT EXISTS produtos_catalogo (product_id
      VARCHAR(64) PRIMARY KEY, nome TEXT, preco NUMERIC, disponivel BOOLEAN,
      last_synced_at TIMESTAMPTZ)` em `ensure_schema()`
- [x] 2.2 `Database.upsert_catalog_products(products: list[dict]) -> None`
      — upsert por `product_id`
- [x] 2.3 `Database.resolve_catalog_items(product_ids: list[str]) ->
      list[dict]` — `SELECT ... WHERE product_id = ANY(%s)`

## 3. Job de sincronização

- [x] 3.1 Novo job (mesmo padrão de `windmill/f/whatbot/check_queue.py`)
      chamando `fetch_catalog()` + `upsert_catalog_products()`
- [x] 3.2 Log/alerta quando a sincronização falha (não deve derrubar o job,
      só deixar o cache desatualizado — próxima execução tenta de novo)

## 4. Testes

- [x] 4.1 `fetch_catalog()` contra fake HTTP: sucesso e falha de rede
- [x] 4.2 Upsert idempotente: rodar duas vezes com o mesmo catálogo não
      duplica linhas, atualiza `last_synced_at`
- [x] 4.3 `resolve_catalog_items` com ids desconhecidos retorna lista
      parcial (não levanta erro para id que não está no cache)
- [x] 4.4 Suíte completa verde (`make test` / `pytest -q`)
