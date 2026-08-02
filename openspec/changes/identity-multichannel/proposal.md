# Identidade de contato multicanal

## Why

Hoje `contatos.phone VARCHAR(32) UNIQUE NOT NULL` é a única chave de
identidade do sistema. Todo módulo que resolve, cria ou normaliza um contato
assume que o identificador é um telefone: `main.py` chama
`get_contact_by_phone`/`create_contact` com o identificador cru,
`normalize_phone` remove tudo que não é dígito, `extract_phone_from_text`
casa qualquer sequência de 10 a 15 dígitos, `should_respond_to_customer`
decide pela lista de teste comparando telefones, e `message_log.py` grava
toda entrada com um campo `phone`.

Isso é o bloqueio de raiz para qualquer canal que não seja WhatsApp. Se um
IGSID (identificador do Instagram) entrasse hoje por esse caminho:

- Colidiria com a chave única de `contatos.phone` — um IGSID numérico de 17
  dígitos viraria literalmente um "telefone".
- Seria normalizado e comparado como telefone silenciosamente, sem erro.
- Poderia ser casado por engano por `extract_phone_from_text` num comando da
  secretaria.
- Seria bloqueado por `should_respond_to_customer` em `TEST_MODE`, porque a
  lista de teste é phone-only.
- Não teria como ser filtrado ou correlacionado em `message_log.py`, porque
  não existe campo `canal`.

Prova executável do problema: `whatbot/main.py:215-219`
(`process_customer_message`) trata o IGSID como se fosse um telefone ao
chamar `get_contact_by_phone`/`create_contact` — e `tests/fakes.py`
replica a mesma limitação, o que faz `tests/test_main_e2e.py` "funcionar"
mesmo com a colisão de identidade presente.

Este change não é específico de Instagram — é a fundação que qualquer canal
além do WhatsApp precisa. Por isso vive numa capability própria (`identity`),
separada de `instagram`.

## What Changes

- Migração aditiva e idempotente em `ensure_schema()`: `contatos` ganha
  `canal`, `external_id`, `handle`, `last_inbound_at`; backfill de todo
  contato existente para `canal='whatsapp'`, `external_id=phone`; chave única
  passa a ser `(canal, external_id)`; `phone` deixa de ser `NOT NULL` e passa
  a ser `NULL` para contatos que não são WhatsApp (ver `design.md`, Decisão
  3). `handover_historico` recebe o mesmo tratamento (Decisão 5). Duas
  tabelas novas, usadas só a partir de `instagram-ingestion-service`, também
  são criadas aqui: `canal_credenciais` e `webhook_eventos` (Decisão 7).
- `Contact` e `WaitingContact` ganham `canal`, `external_id`, `handle`, e um
  rótulo legível com precedência nome → arroba/handle → identidade externa.
- Métodos de `whatbot/db.py` passam a operar por `(canal, external_id)`, com
  compatibilidade assumindo `whatsapp` quando o canal não for informado.
- `normalize_phone` (`whatbot/queue.py`, `whatbot/main.py`) restrito a
  identidades de WhatsApp; `extract_phone_from_text`
  (`whatbot/contact_resolver.py`) deixa de casar identificadores de outros
  canais.
- `should_respond_to_customer` (`whatbot/config.py`) passa a filtrar por
  `(canal, external_id)`, com lista de teste própria por canal
  (`TEST_PHONES` para WhatsApp, `TEST_IGSIDS` para Instagram), fail-closed
  quando o canal não tem lista configurada (Decisão 6).
- `whatbot/message_log.py`: `log_inbound`, `log_outbound` e `log_llm_turn`
  ganham campo `canal` em toda entrada, incluindo o resumo textual que hoje
  imprime `phone=`.
- **`whatbot/admin.py` entra no escopo** (Decisão 4): todo call site que
  assume `phone` como identidade (`assumir_contato`, `mark_attended`,
  `reativar_bot`, `search_contacts_for_admin`, resolução de comando por
  `extract_phone_from_text`) é auditado e corrigido para não quebrar com
  contatos não-WhatsApp.
- `whatbot/contact_resolver.py:43` e os pontos de `whatbot/queue.py` que
  interpolam `contact.phone` diretamente (incluindo
  `process_auto_reactivations`) são corrigidos para tolerar `phone=None`.
- `whatbot/domain.py:115` (`executar_handover_para_secretaria`) passa a usar
  o `canal` que já recebe como parâmetro (hoje ignorado na consulta ao
  banco), evitando falha silenciosa de handover para contatos não-WhatsApp.
- `tests/fakes.py::FakeDatabase` migra para a chave composta, corrigindo o
  hack de IGSID-como-telefone hoje presente em `whatbot/main.py:215-219`.

**Sem unificação de pessoa entre canais nesta fase.** Um mesmo humano que
fala pelo WhatsApp e pelo Instagram gera dois contatos distintos — a chave é
`(canal, external_id)`, não uma pessoa. Unificação de identidade humana entre
canais fica para um change futuro, especulativo, a validar com dados reais
de uso (ex.: taxa de contatos que aparecem nos dois canais).

## Impact

- Specs afetadas: `identity` (nova capability)
- Código alterado: `whatbot/db.py` (schema e todos os métodos de contato),
  `whatbot/queue.py`, `whatbot/contact_resolver.py`, `whatbot/config.py`,
  `whatbot/message_log.py`, `whatbot/main.py` (pontos que chamam
  `get_contact_by_phone`/`create_contact`, `_ensure_admin_contact`,
  `run_admin_simulation`, `is_admin_phone`), `whatbot/domain.py`
  (`executar_handover_para_secretaria`), `whatbot/admin.py` (comandos que
  resolvem contato por telefone)
- Testes alterados: `tests/fakes.py::FakeDatabase`, `tests/test_main_e2e.py`
  (remove o hack de IGSID-como-phone em `main.py`), `tests/test_test_mode.py`
  (não `tests/test_config.py`, que não existe), `tests/test_message_log.py`
- Teste novo: migração de schema contra Postgres real, fora da descoberta de
  `make test` (ver `tasks.md` para localização e critério de aceite)
- Sem regressão no WhatsApp: a migração é aditiva, e todo código que já
  assume `whatsapp` continua funcionando sem informar canal explicitamente
- Bloqueia: `channel-queue-visibility`, `instagram-messaging-window`,
  `instagram-ingestion-service`, `instagram-go-live`,
  `instagram-operability` (todos dependem de existir onde guardar
  `canal`/`external_id`/`last_inbound_at`/`webhook_eventos`/
  `canal_credenciais`). **Não bloqueia `instagram-channel-client`** — o
  cliente e o parser do Instagram não tocam `db.py`, podem ser
  desenvolvidos em paralelo com este change (ver
  `instagram-channel-client/proposal.md`).
