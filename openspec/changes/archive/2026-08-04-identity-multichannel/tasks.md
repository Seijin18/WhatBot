# Tasks — identidade de contato multicanal

## 1. Schema

- [x] 1.1 Migração aditiva e idempotente dentro de `ensure_schema()`:
      `canal VARCHAR(32)`, `external_id VARCHAR(64)`, `handle VARCHAR(128)`,
      `last_inbound_at TIMESTAMP WITH TIME ZONE` em `contatos`; backfill
      (`canal='whatsapp'`, `external_id=phone` onde `canal IS NULL`);
      `ALTER TABLE contatos ALTER COLUMN phone DROP NOT NULL`; manter a
      `UNIQUE` de `phone` (não conflita com múltiplos `NULL` em Postgres);
      `external_id` vira `NOT NULL` só depois do backfill; índice único em
      `(canal, external_id)`
      (→ Requirement "Identidade do contato por canal")
- [x] 1.2 Mesmo tratamento em `handover_historico`: `canal`, `external_id`;
      `ALTER COLUMN phone DROP NOT NULL`; backfill igual à 1.1
      (→ Requirement "Identidade do contato por canal", cenário "Migração de
      base existente")
- [x] 1.3 Criar as duas tabelas usadas a partir de
      `instagram-ingestion-service` (ver `design.md`, Decisão 7):

      ```sql
      CREATE TABLE IF NOT EXISTS canal_credenciais (
          canal VARCHAR(16) PRIMARY KEY,
          account_id VARCHAR(64),
          access_token TEXT NOT NULL,
          expires_at TIMESTAMP WITH TIME ZONE,
          refreshed_at TIMESTAMP WITH TIME ZONE DEFAULT now()
      );

      CREATE TABLE IF NOT EXISTS webhook_eventos (
          canal VARCHAR(16) NOT NULL,
          message_id VARCHAR(128) NOT NULL,
          received_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
          PRIMARY KEY (canal, message_id)
      );
      CREATE INDEX IF NOT EXISTS webhook_eventos_received_idx
          ON webhook_eventos (received_at);
      ```

      (DDL herdado de `docs/INSTAGRAM_INTEGRATION_PLAN.md`, seção de
      migração — os requisitos de `instagram-ingestion-service` descrevem o
      *comportamento* que essas tabelas sustentam, não o schema; o schema
      vive só aqui, no change que altera `ensure_schema()`)

## 2. Camada de dados

- [x] 2.1 `Contact` e `WaitingContact` ganham `canal`, `external_id`,
      `handle`, com valores-default (para não quebrar construção existente
      via kwargs parciais), e o rótulo legível (nome → handle → identidade
      externa)
      (→ Requirement "Rótulo legível de contato")
- [x] 2.2 `_archive_handover` grava `(canal, external_id)` em
      `handover_historico`
      (→ Requirement "Identidade do contato por canal")
- [x] 2.3 Reescrever, um a um, os métodos de `whatbot/db.py` que hoje
      recebem `phone` como identidade, para operar por
      `(canal, external_id)` com compatibilidade assumindo `whatsapp`
      quando o canal não vier: `get_contact_by_phone`, `create_contact`,
      `is_waiting`, `get_contact_waiting`, `enroll_handover`,
      `mark_attended`, `assumir_contato`, `reativar_bot`,
      `process_auto_reactivations`, `search_contacts_for_admin`
      (→ Requirement "Identidade do contato por canal")
- [x] 2.4 `create_contact`: decidir e documentar se `phone=` continua kwarg
      válido para chamadores WhatsApp (compat de assinatura) ou se todo call
      site passa a usar `external_id=`/`canal=` explicitamente

## 3. Normalização

- [x] 3.1 `normalize_phone` (`whatbot/main.py`, `whatbot/queue.py`) só roda
      para `canal == "whatsapp"` ou canal não informado — inclui o call site
      de `is_admin_phone` (`whatbot/main.py:539`) e de
      `run_admin_simulation` (`whatbot/main.py:153-154`), que hoje normalizam
      incondicionalmente mesmo quando `canal` já é conhecido
      (→ Requirement "Normalização de identidade específica por canal")
- [x] 3.2 `extract_phone_from_text` (`whatbot/contact_resolver.py:24-26`)
      deixa de casar identificadores de outros canais
      (→ idem)

## 4. Consumidores de `contact.phone` que precisam tolerar `None`

- [x] 4.1 `whatbot/contact_resolver.py:43` (`c.phone.endswith(...)`) e
      `:74` (rótulo em `format_disambiguation`) passam a usar o rótulo
      legível em vez de assumir `phone` presente
      (→ Requirement "Contato de canal não-WhatsApp não usa `phone`")
- [x] 4.2 `whatbot/queue.py`: notificação de novo item, listagem da fila
      (`format_waiting_list`) e `process_auto_reactivations` (que hoje monta
      uma lista a partir de `RETURNING phone`) passam a tolerar `phone=None`
      sem quebrar — usam o rótulo legível como fallback
      (→ idem; a exibição de canal na fila é escopo de
      `channel-queue-visibility`, este change só garante que nada quebra)
- [x] 4.3 `whatbot/admin.py`: auditar e corrigir todo call site que assume
      `phone` como identidade — `assumir_contato`, `mark_attended`,
      `reativar_bot`, resolução de comando via `extract_phone_from_text`,
      `search_contacts_for_admin` — para operar por `(canal, external_id)`
      ou tolerar `phone=None` conforme o caso
      (→ Requirement "Identidade do contato por canal"; ver `design.md`,
      Decisão 4)
- [x] 4.4 `whatbot/domain.py:115` (dentro de
      `executar_handover_para_secretaria`, que já recebe `canal` como
      parâmetro em `domain.py:76` mas não o usa na consulta) passa a chamar
      `get_contact_waiting` com o canal correto

## 5. Filtro de teste e observabilidade

- [x] 5.1 `should_respond_to_customer` (`whatbot/config.py:144`) decide por
      `(canal, external_id)`, com `TEST_PHONES` (WhatsApp) e `TEST_IGSIDS`
      (Instagram) como listas por canal, fail-closed quando a lista do canal
      não está configurada
      (→ Requirement "Filtro de teste por canal")
- [x] 5.2 `log_inbound`, `log_outbound`, `log_llm_turn`
      (`whatbot/message_log.py`) ganham parâmetro nomeado `canal`,
      incluindo no resumo textual que hoje imprime só `phone=`
      (→ Requirement "Rastreabilidade por canal no log de mensagens")

## 6. Testes

- [x] 6.1 Atualizar `tests/fakes.py::FakeDatabase` para chave composta
      `(canal, external_id)`, sem quebrar asserções hoje verdes que não
      dependem de identidade
- [x] 6.2 Corrigir o hack de IGSID-como-`phone` em `whatbot/main.py:215-219`
      (ver `design.md`, seção "Evidência do problema atual") — contato de
      Instagram passa a ser criado com `canal="instagram"`,
      `external_id=IGSID`, `phone=None`
      (→ Requirement "Identidade do contato por canal", cenário "Contato de
      canal não-WhatsApp não usa `phone`")
- [x] 6.3 `tests/test_test_mode.py` (não `tests/test_config.py`, que não
      existe): `should_respond_to_customer` com lista de teste por canal,
      incluindo os três cenários do requirement "Filtro de teste por canal"
- [x] 6.4 `tests/test_message_log.py`: toda entrada de log carrega `canal`
- [x] 6.5 Testes de `tests/test_contact_resolver.py` e `tests/test_queue.py`
      (ou arquivos equivalentes) cobrindo contato com `phone=None`: fila,
      disambiguation e reativação automática não quebram
- [x] 6.6 Testes de `whatbot/admin.py` cobrindo comando de assumir/finalizar
      um contato não-WhatsApp
- [x] 6.7 Teste cobrindo "Mesma identidade externa em canais diferentes":
      criar dois contatos com o mesmo `external_id` em canais diferentes,
      sem colisão
- [x] 6.8 **Teste de migração contra Postgres real**
      (→ Requirement "Identidade do contato por canal", cenário "Migração de
      base existente"). Especificação:
      - Vive em `tests/integration/test_identity_migration.py`, **fora** da
        descoberta de `make test` (`python -m unittest discover -s tests`
        varre só `tests/`, não subpastas com `__init__.py` ausente — ou,
        alternativa mais simples, prefixar o arquivo para não casar
        `test_*.py` na raiz de `tests/` e documentar o comando específico no
        `Makefile`, ex.: `make test-migration`)
      - Pulado automaticamente (via `unittest.skip`/`SkipTest`) quando a DSN
        de teste (`WHATBOT_TEST_DSN` ou equivalente) não está configurada —
        não quebra `make test` em ambiente sem Postgres
      - Provisiona contra o serviço `db` do `docker-compose.yml`, em schema
        ou banco descartável criado no `setUp` e derrubado no `tearDown`
      - Popula a base no formato antigo (tabela `contatos` e
        `handover_historico` sem as colunas novas, ou com elas ausentes)
      - Roda `ensure_schema()`, compara dump ordenado de `contatos` e de
        `handover_historico` antes/depois: nenhuma linha perdida,
        `canal`/`external_id` corretos
      - Roda `ensure_schema()` uma segunda vez, compara o dump de novo:
        idêntico ao da primeira execução
      - Tenta inserir um `(canal, external_id)` duplicado: rejeitado pela
        constraint única
- [x] 6.9 Suíte completa (`make test`) verde, sem alteração de asserção fora
      dos arquivos tocados nesta lista
