# Contato tem tipo de cliente: B2C ou B2B

## Why

Hoje todo contato em `contatos` é tratado da mesma forma, independente de
ser uma pessoa física (aluno/associado individual) ou uma empresa
(parceria, compra corporativa, etc.). Não existe nenhum campo que
diferencie isso — só `status`, que descreve o ciclo de vida do lead
(`novo_lead`/`matriculado`/`cancelado`), um eixo ortogonal. Sem essa
distinção, não é possível segmentar atendimento, relatórios ou campanhas
por tipo de cliente.

## What Changes

- Nova coluna `contatos.tipo_cliente VARCHAR(8) NOT NULL DEFAULT 'b2c'`,
  adicionada em `ensure_schema()` (`whatbot/db.py`) pelo mesmo padrão
  idempotente já usado para as demais colunas aditivas (`ALTER TABLE ADD
  COLUMN IF NOT EXISTS`). Validação dos dois valores permitidos (`b2c`,
  `b2b`) fica em Python, não em `CHECK` constraint — mesmo padrão de
  `status`/`canal`, que também não têm constraint de banco.
- `Contact` (dataclass em `whatbot/db.py`) ganha o campo `tipo_cliente`.
- Novo método `Database.set_contact_tipo_cliente(contact_id: int,
  tipo_cliente: str) -> None`.
- `Database.search_contacts_for_admin()` passa a incluir `tipo_cliente` no
  dict retornado, para exibição em listas do admin.
- Novo comando em linguagem natural do admin para marcar o tipo de um
  contato (ex.: "marca a Maria como empresa", "marca o João como pessoa
  física", "define Maria como B2B") — nova intenção `set_tipo_cliente` em
  `whatbot/admin_nlu.py`, resolução de contato reaproveitando
  `search_contacts_for_admin` com o mesmo padrão de desambiguação já usado
  por `_resolve_reactivate` (`whatbot/admin.py`).

## Impact

- Specs afetadas: `contacts` (capability nova)
- Código alterado: `whatbot/db.py`, `whatbot/admin_nlu.py`, `whatbot/admin.py`
- Testes alterados: suíte de `whatbot/db.py` (ou equivalente),
  `tests/test_admin_organic.py`
- Bloqueado por: nenhum
- Acoplamento leve e não bloqueante com o change `campaign-csv-broadcast`:
  a importação de CSV daquele change pode opcionalmente chamar
  `set_contact_tipo_cliente` se uma coluna `tipo_cliente` vier no arquivo —
  este change não depende disso para ser implementado sozinho, e o outro
  change funciona (com default `b2c`) mesmo que este não tenha sido
  implementado ainda.

## Fora de escopo (decisão explícita)

- Prompt de sistema diferente por `tipo_cliente` (hoje `SYSTEM_PROMPTS` é
  indexado por `status`, não por tipo de cliente) — não faz parte deste
  change; se a operação mostrar necessidade real, tratar em change futuro.
- Filtro de `tipo_cliente` na listagem da fila (`whatbot/queue.py`) — a
  fila é sobre atendimento pendente, não sobre segmentação comercial; fora
  de escopo pelo mesmo motivo que `channel-queue-visibility` deixou de fora
  exibições não essenciais ao risco que motivou aquele change.
