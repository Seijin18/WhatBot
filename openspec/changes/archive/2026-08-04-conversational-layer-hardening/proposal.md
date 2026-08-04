## Why

O ciclo intenção → conhecimento → prompt → validação → resposta (`whatbot/intent_router.py`,
`whatbot/knowledge*.py`, `whatbot/prompt_builder.py`, `whatbot/reply_composer.py`,
`whatbot/grounding.py`, `whatbot/claim_validator.py`) nunca teve uma spec. Ele foi
escrito para uma associação esportiva (modalidades, aula experimental, plano
mensal/semestral) e continuou com esse comportamento mesmo depois de
`knowledge/associacao.md` ser trocado para um negócio de encomendas sem esses
conceitos — porque nada especificava os invariantes que deveriam sobreviver à
troca de conteúdo. Uma auditoria (`docs/REVISAO_CAMADA_CONVERSACIONAL.md`)
encontrou a LLM recebendo contexto vazio nas aberturas de conversa, um gatilho
que substituía toda resposta de preço por template sem chamar o modelo, um
detector de alucinação que reprovava respostas corretas, e um FAQ que devolvia
a pergunta errada. Sem spec, esses defeitos não tinham como ser pegos por
revisão — a suíte de teste também dependia do conteúdo de produção do KB e
quebrou inteira na mesma troca.

## What Changes

- Base de conhecimento completa (não fatiada por intenção) sempre entra no
  prompt da LLM — remove o gatilho que enviava contexto vazio para
  saudação/pergunta fora do script.
- Nenhuma intenção substitui a resposta da LLM por template antes de gerá-la;
  correção factual acontece só depois, sobre o texto já gerado.
- Detecção de alucinação e validação de reivindicações operam sobre fatos
  citados (números, nomes, dias) — não sobre presença/ausência de vocabulário
  livre — e nunca reprovam uma resposta livre de reivindicações verificáveis.
- Rótulos de seção no prompt e nas respostas vêm do cabeçalho real do arquivo
  de conhecimento, não de tradução fixa no código.
- Roteamento de intenção usa vocabulário curado (não "toda palavra da seção
  correspondente") e cobre pedido/pagamento/entrega além de preço/horário.
- Toda mensagem fixa ao cliente (indisponibilidade, handover, fallback) é
  genérica quanto ao tipo de negócio.
- **BREAKING** (interno, não afeta clientes): `whatbot/booking_flow.py` (código
  morto, sem nenhum import) foi removido.

## Capabilities

### New Capabilities

- `conversa`: o ciclo intenção → conhecimento → prompt → validação → resposta
  que decide o que o bot diz a um cliente, incluindo os invariantes que
  precisam sobreviver a qualquer conteúdo de `knowledge/*.md`.

### Modified Capabilities

(nenhuma — `channels` não muda)

## Impact

- Código: `whatbot/intent_router.py`, `whatbot/knowledge.py`,
  `whatbot/knowledge_facts.py`, `whatbot/prompt_builder.py`,
  `whatbot/reply_composer.py`, `whatbot/grounding.py`,
  `whatbot/claim_validator.py`, `whatbot/session_state.py`,
  `whatbot/fallback.py`, `whatbot/domain.py`, `whatbot/priority.py`,
  `whatbot/admin.py`, `whatbot/tools.py`, `whatbot/main.py`
- Removido: `whatbot/booking_flow.py`
- Testes: `tests/kb_fixtures.py` (novo — duas bases sintéticas, uma por
  formato de negócio suportado), `tests/test_knowledge.py`,
  `tests/test_domain.py`, `tests/test_grounding.py` reescritos para não
  depender de `knowledge/associacao.md`
- Specs: cria `openspec/specs/conversa/spec.md`
