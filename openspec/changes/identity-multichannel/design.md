# Design — identidade de contato multicanal

## Decisão 1: chave `(canal, external_id)`, sem unificação de pessoa

Alternativas consideradas:

1. **Unificar pessoa entre canais** (uma tabela `pessoas` com N vínculos de
   canal). Rejeitada nesta fase: exige decidir agora uma heurística de
   correspondência (nome? telefone informado no perfil do Instagram?
   confirmação manual da secretaria?) sem dado real de quantos contatos
   realmente aparecem nos dois canais. O risco de casar duas pessoas
   diferentes por engano — misturando histórico de atendimento — é maior que
   o custo de manter dois registros por enquanto. Confirmado com o usuário:
   fica para um change futuro, especulativo.
2. **Só um campo `canal` como coluna nova, mantendo `phone` como chave.**
   Rejeitada: um IGSID não é um telefone, forçar os dois no mesmo formato
   reintroduz o problema de normalização que este change resolve.
3. **`(canal, external_id)` como chave composta, `phone` preservado como
   coluna não-chave.** Escolhida. É a decisão já registrada em
   `docs/INSTAGRAM_INTEGRATION_PLAN.md` (Decisão 3). Migração aditiva:
   nenhuma linha existente perde `phone`, só ganha `canal='whatsapp'` e
   `external_id=phone` como equivalentes.

## Decisão 2: migração aditiva e idempotente, não uma reescrita

`ensure_schema()` já roda a cada início do processo (`whatbot/db.py:69-131`,
chamado a cada `_init_infra()` — ver `whatbot/main.py:82`). A migração deste
change segue o mesmo padrão: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`,
backfill condicional (`UPDATE ... WHERE canal IS NULL`), e criação de índice
único só se ainda não existir. Rodar a migração duas vezes seguidas não deve
alterar nada na segunda vez — é o critério de aceite do teste de migração
(`tasks.md`, tarefa 6.8). Esse teste vive em `tests/integration/`, fora da
descoberta de `make test` (`python -m unittest discover -s tests`, que não
varre subpastas sem `__init__.py`); `pytest -q` **coletaria** essa pasta, mas
o teste se autoexclui via `SkipTest` quando a DSN de teste não está
configurada, então o comportamento observável é o mesmo nas duas formas de
rodar a suíte.

`CREATE TABLE IF NOT EXISTS contatos` continua criando `phone UNIQUE NOT
NULL` para uma base nova (intencional — os `ALTER`s seguintes relaxam essa
constraint tanto em base nova quanto existente, então o comportamento final é
o mesmo independente de a tabela já existir ou não).

## Decisão 3: `contatos.phone` vira `NULL` para contatos que não são WhatsApp

Esta é a decisão que faltava na primeira versão deste change — sem ela, dois
caminhos reais quebram:

- Se `phone` recebesse `external_id` de qualquer canal (ex.: o IGSID), a
  colisão contra a `UNIQUE` de `phone` reapareceria assim que dois contatos
  de canais diferentes tivessem identificadores textualmente iguais — exatamente
  o problema que este change existe para eliminar.
- Se `phone` ficasse com um valor arbitrário, qualquer consumidor de
  `.phone` fora do escopo do canal WhatsApp exibiria ou compararia lixo.

**Escolha: `phone = NULL` para contatos com `canal != "whatsapp"`.** A
constraint `NOT NULL` em `contatos.phone` é relaxada
(`ALTER TABLE contatos ALTER COLUMN phone DROP NOT NULL`), mantendo a
`UNIQUE` (Postgres trata múltiplos `NULL` como não-conflitantes numa coluna
`UNIQUE`, então isso não bloqueia a criação de vários contatos
não-WhatsApp).

**Nota de reconciliação com `docs/INSTAGRAM_INTEGRATION_PLAN.md`**: o SQL
narrativo daquele documento (seção de migração) também dropa a constraint
(`ALTER TABLE contatos DROP CONSTRAINT IF EXISTS contatos_phone_key`). Este
change **não** faz esse `DROP CONSTRAINT` — manter a `UNIQUE` é
estritamente mais seguro (impede duas linhas com o mesmo `phone` não-nulo
por acidente) e não tem custo, já que `NULL`s múltiplos já são permitidos.
O documento narrativo fica superado neste ponto específico; `tasks.md` 1.1 é
a fonte de verdade.

Todo consumidor de `contact.phone` que não filtra por canal precisa ser
auditado e corrigido para usar o rótulo legível (`channel_label()` +
identidade externa) em vez de assumir que `.phone` sempre tem valor. Os
pontos concretos identificados na auditoria de código deste change (ver
`tasks.md`, seção 4):

- `whatbot/contact_resolver.py:43` — `c.phone.endswith(...)` quebra com
  `phone=None`
- `whatbot/queue.py` — `process_auto_reactivations()` (retorna `phone` via
  `RETURNING phone`) e as strings de notificação que interpolam
  `contact.phone` diretamente
- `whatbot/admin.py` — ver Decisão 4

## Decisão 4: `whatbot/admin.py` entra no escopo deste change

Auditoria de código encontrou 61 ocorrências de `phone` em `whatbot/admin.py`,
incluindo chamadas diretas aos métodos que este change reescreve:
`assumir_contato`, `mark_attended`, `reativar_bot`,
`search_contacts_for_admin`, além de `extract_phone_from_text` (alterado pela
tarefa de normalização). Sem cobrir `admin.py`, a secretaria fica sem
comando para assumir ou finalizar atendimento de um contato de Instagram
assim que `channel-queue-visibility` passar a listá-lo na fila — furo que
qualquer um dos changes seguintes herdaria silenciosamente.

Alternativa considerada — criar um change à parte só para `admin.py` — foi
rejeitada: `admin.py` consome exatamente os mesmos métodos de `db.py` que
este change já está reescrevendo; separar obrigaria a manter dois changes
sincronizados sobre a mesma API em transição.

## Decisão 5: `handover_historico.phone` também vira nullable, com backfill

`handover_historico.phone VARCHAR(32) NOT NULL` (`whatbot/db.py:109`) é
gravado por `_archive_handover` toda vez que `mark_attended` roda. Sem
relaxar essa constraint e sem gravar `(canal, external_id)` nessa tabela, o
arquivamento de um atendimento de Instagram falha com violação de NOT NULL —
a secretaria não consegue finalizar o atendimento. `handover_historico` ganha
as mesmas colunas `canal`/`external_id` de `contatos`, com o mesmo backfill
(`canal='whatsapp'`, `external_id=phone` para linhas existentes), e
`_archive_handover` passa a gravá-las.

## Decisão 6: regra de teste por canal é uma função por canal, não um `THEN` ambíguo

A primeira versão da spec dizia "a decisão é explícita (bloquear ou
responder, conforme a política padrão do canal)" — não verificável, porque
aceita os dois resultados opostos. A regra final: `TEST_MODE` continua
global (liga/desliga a checagem para todo canal); dentro dele, cada canal
tem sua própria variável de lista de teste (`TEST_PHONES` já existe para
WhatsApp; Instagram usa `TEST_IGSIDS`, seguindo a mesma convenção de nome).
Um canal sem variável de lista configurada, em `TEST_MODE`, **bloqueia por
padrão** (fail-closed) — é o comportamento mais seguro: enviar de menos numa
integração ainda não configurada é reversível, enviar de mais para um
público não pretendido não é.

## Decisão 7: `canal_credenciais` e `webhook_eventos` são criadas aqui

Essas duas tabelas são consumidas por `instagram-ingestion-service`
(autenticidade/idempotência de webhook e renovação de credencial), mas a
criação delas fica neste change, não naquele — porque este é o único change
da sequência que altera `ensure_schema()`. Ter dois changes diferentes
alterando a mesma função de schema seria mais arriscado (ordem de aplicação
importa, testes de migração fragmentados) do que este change ficar
responsável por toda a superfície de schema necessária à sequência inteira,
mesmo a parte que só será consumida depois. `instagram-ingestion-service`
referencia essas tabelas como pré-existentes e não as recria.

## Decisão 8: rótulo legível como contrato, não como implementação de fila

`channel_label()` já existe em `whatbot/channels/base.py:48` mas está
órfão — nenhum código de produção o chama (confirmado por auditoria: único
consumidor hoje é `tests/test_channel_router.py`). Este change define o
contrato (precedência nome → arroba/handle → identidade externa) como parte
da capability `identity`; o consumo real na fila e nas notificações é
responsabilidade de `channel-queue-visibility`, que depende deste change mas
não faz parte dele.

## Evidência do problema atual

O IGSID de teste em `tests/test_main_e2e.py` (`IGSID =
"17841400000000000"`, linha 23) é passado hoje no parâmetro posicional
`phone` de `process_customer_message(IGSID, ..., canal=INSTAGRAM)`
(`whatbot/main.py:215-219`), que por sua vez chama
`db.get_contact_by_phone(phone)` / `db.create_contact(phone=phone, ...)`.
Ou seja: o "hack" não está no arquivo de teste em si — está em
`whatbot/main.py:215-219`, propagado pelo fato de `FakeDatabase`
(`tests/fakes.py`) replicar a mesma limitação de `phone`-como-chave-única do
banco real. Isso corrige uma leitura anterior deste documento que descrevia
incorretamente o "hack" como estando no arquivo de teste — a correção real
tem que tocar `main.py` e `tests/fakes.py`, não só as asserções do teste.

## Não-objetivos

- Unificação de pessoa entre canais (ver Decisão 1).
- Suporte a um terceiro canal além de WhatsApp/Instagram — o schema é
  genérico o bastante para acomodar, mas nenhuma tarefa aqui cria código
  específico de um terceiro canal.
