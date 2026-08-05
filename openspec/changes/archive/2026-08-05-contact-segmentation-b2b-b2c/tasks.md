# Tasks — contato tem tipo de cliente B2C/B2B

## 1. Schema

- [x] 1.1 `ALTER TABLE contatos ADD COLUMN IF NOT EXISTS tipo_cliente
      VARCHAR(8) NOT NULL DEFAULT 'b2c';` em `ensure_schema()`
      (`whatbot/db.py`) — migração aditiva e idempotente, mesmo padrão das
      colunas anteriores (→ Requirement "Contato tem tipo de cliente")
- [x] 1.2 `Contact` (dataclass) ganha `tipo_cliente: str = "b2c"`;
      `_row_to_contact` e o `_CONTACT_SELECT` passam a ler a nova coluna

## 2. Camada de dados

- [x] 2.1 `Database.set_contact_tipo_cliente(contact_id: int, tipo_cliente:
      str) -> None` — valida `tipo_cliente in {"b2c", "b2b"}` antes do
      `UPDATE`, levanta `ValueError` para qualquer outro valor
- [x] 2.2 `Database.search_contacts_for_admin()` inclui `tipo_cliente` no
      dict de cada linha retornada

## 3. Comando de admin

- [x] 3.1 Nova intenção `set_tipo_cliente` em `whatbot/admin_nlu.py`,
      capturando o alvo (nome/telefone) e o tipo desejado (ex.: "empresa"/
      "b2b" → `"b2b"`, "pessoa física"/"b2c" → `"b2c"`)
- [x] 3.2 Resolução do contato-alvo em `whatbot/admin.py` reaproveitando
      `search_contacts_for_admin` (sem filtro por `ia_ativa` — aqui
      qualquer contato é um alvo válido, ao contrário de
      `_resolve_reactivate`), com desambiguação via `db.save_admin_sessao`
      quando houver mais de um resultado, mesmo padrão de
      `_resolve_reactivate`
- [x] 3.3 `_execute_action` (ou branch equivalente em
      `handle_admin_message`) chama `db.set_contact_tipo_cliente` e
      responde confirmando o novo tipo ao admin

## 4. Testes

- [x] 4.1 Migração idempotente: rodar `ensure_schema()` duas vezes não
      altera contatos existentes; contato pré-existente fica com `b2c`
      (default) após a migração
- [x] 4.2 `set_contact_tipo_cliente` rejeita valor fora de `{"b2c", "b2b"}`
- [x] 4.3 Comando "marca a Maria como empresa" com um único resultado
      atualiza direto; com múltiplos resultados, desambigua igual ao fluxo
      de `reactivate`
- [x] 4.4 Suíte completa verde (`make test` / `pytest -q`)
