## Why

O sweep anterior (`conversational-layer-hardening`) tratou headings e
identificadores isolados ("Sobre a associação", "Matrícula e pagamentos",
`ASSOCIACAO_KNOWLEDGE_PATH`), mas deixou intocado o substantivo central do
esquema: **"modalidade"** é o nome da classe que representa qualquer item
cadastrado no `## Modalidades` do arquivo de conhecimento — mesma
categoria estrutural das duas seções já renomeadas, só que maior (~154
ocorrências em 9 arquivos de `whatbot/`, incluindo um heading obrigatório
do `.md` e texto injetado no prompt da LLM).

Além do nome, há um problema de arquitetura mais sério:
`SessionState.modalidade_interesse` (a memória de "o que o cliente
demonstrou interesse" entre turnos) é atualizado por uma heurística de
texto independente — `session_state.py::update_session_state` chama
`knowledge_facts.match_modalidades(user_message)` do zero, em vez de
reaproveitar `IntentResult.modalities`, que `intent_router.py::route_intent`
**já calculou** um passo antes, no mesmo turno, com a mesma lógica mais o
merge com a sessão. São dois heurísticos paralelos e ligeiramente
diferentes (um deles também varre as últimas 6 mensagens do histórico)
que podem divergir no mesmo turno — não é só um problema de nome, é uma
duplicação real com potencial de inconsistência entre o que a intenção
"decidiu" e o que a sessão "lembra".

## What Changes

- Rename mecânico "modalidade" → "item" em `whatbot/knowledge.py`,
  `knowledge_facts.py`, `session_state.py`, `reply_composer.py`,
  `claim_validator.py`, `grounding.py`, `fallback.py`, `tools.py`:
  dataclass, heading obrigatório do `.md` (`## Modalidades` → `## Itens`),
  texto injetado no prompt ("Modalidade: {nome}" → "Item: {nome}"),
  ~10 funções/campos (`match_modalidades`, `modalidade_interesse`,
  `listar_modalidades` — esta última também é o nome de uma tool exposta
  ao Gemini). Palavras-gatilho de conteúdo que um cliente digitaria
  ("quais modalidades vocês têm?") continuam existindo — só o
  identificador/schema muda, mesma distinção já aplicada no sweep
  anterior.
- **BREAKING** (interno, não afeta clientes nem o `.env`): qualquer
  arquivo de conhecimento já em produção usando `## Modalidades` como
  heading precisa ser atualizado para `## Itens` no deploy desta mudança
  — é uma chave estrutural fixa que o parser procura, não só prosa.
- `update_session_state` para de receber `user_message`/`history` e de
  chamar `get_knowledge_facts()` — passa a receber `intent` e `items`
  (já resolvidos por `route_intent`) como parâmetros simples, eliminando
  o segundo heurístico duplicado e o fallback de varredura de histórico
  (redundante: a sessão já carrega o item adiante via
  `resolve_items(text, session.item_interesse)`).
- Novo teste de regressão de vocabulário (mesmo padrão de
  `tests/test_no_association_leftovers.py`) para "modalidade" como
  identificador, com allowlist para as palavras-gatilho de conteúdo que
  continuam de propósito.

## Capabilities

### New Capabilities

(nenhuma)

### Modified Capabilities

- `conversa`: adiciona o requisito de que o esquema de conhecimento use
  vocabulário neutro de negócio (não específico de associação esportiva)
  e que o rastreio de interesse entre turnos derive do mesmo evento
  estruturado que decide a intenção, não de uma heurística de texto
  paralela e potencialmente divergente.

## Impact

- Código: `whatbot/knowledge.py`, `whatbot/knowledge_facts.py`,
  `whatbot/session_state.py`, `whatbot/main.py` (chamada de
  `update_session_state`), `whatbot/reply_composer.py`,
  `whatbot/claim_validator.py`, `whatbot/grounding.py`,
  `whatbot/fallback.py`, `whatbot/tools.py`
- Dados: `knowledge/base.md` (heading `## Modalidades` → `## Itens`, se a
  base em produção vier a usar essa seção — hoje o catálogo da Camu não
  tem `## Modalidades`, então o impacto imediato em produção é zero)
- Documentação: `knowledge/README.md` (template)
- Testes: `tests/kb_fixtures.py` (as duas fixtures sintéticas),
  `tests/test_knowledge.py`, `tests/test_grounding.py`,
  `tests/test_domain.py`, novo teste de regressão de vocabulário
- Sem migração de dados: `contatos.session_state` é uma coluna JSONB
  tratada como blob opaco em toda a stack (confirmado em `whatbot/db.py`
  e `tests/fakes.py::FakeDatabase` — nenhum SQL/DDL/fake inspeciona a
  chave `modalidade_interesse` como string literal). Sessões em voo no
  momento do deploy simplesmente não reconhecem a chave antiga e o campo
  volta a ser preenchido no próximo turno.
