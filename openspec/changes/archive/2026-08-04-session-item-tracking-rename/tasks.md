## 1. Esquema de conhecimento (`whatbot/knowledge.py`)

- [x] 1.1 `Modalidade` (dataclass) → `Item`; `KnowledgeBase.modalidades` →
      `KnowledgeBase.itens`; heading obrigatório do parser (`_parse_markdown`,
      `modalidade_buffer`) `## Modalidades` → `## Itens`
- [x] 1.2 `KnowledgeStore._match_modalidade`/`match_modalidades`/
      `listar_modalidades`/`registered_modalidade_names` renomeados (`_match_item`,
      `match_items`, `listar_itens`, `registered_item_names`); textos ao
      cliente ("Modalidade '...' não encontrada", "Modalidades disponíveis:",
      "Nenhuma modalidade cadastrada") viram "Item"/"Itens"
- [x] 1.3 `buscar_horarios`/`buscar_precos` (`KnowledgeStore`): parâmetro
      `modalidade` → `item`; mensagens formatadas atualizadas
- [x] 1.4 Texto injetado no prompt (`Modalidade: {nome}` no formatador do
      item) → `Item: {nome}`

## 2. Fatos derivados (`whatbot/knowledge_facts.py`)

- [x] 2.1 `match_modalidades_in_text` → `match_items_in_text`;
      `_link_label_to_modalidades` → `_link_label_to_items`
- [x] 2.2 `KnowledgeFacts.modalidade_names` → `item_names`;
      `regular_days_by_modalidade` → `regular_days_by_item`
- [x] 2.3 `KnowledgeFacts.match_modalidades`/`resolve_modalidades`/
      `primary_modalidade` → `match_items`/`resolve_items`/`primary_item`;
      parâmetro `session_modalidades` → `session_items`
- [x] 2.4 `ExperimentalSlot.modalidades` → `itens`
- [x] 2.5 Variável interna `modalidade_name_tokens` → `item_name_tokens`
      (vocabulário-gatilho de intenção em português — "modalidade",
      "modalidades" como palavras que um cliente digitaria — permanece
      como está; só o identificador Python muda)

## 3. Sessão e roteamento de intenção — elimina o heurístico duplicado

- [x] 3.1 `whatbot/session_state.py`: `SessionState.modalidade_interesse` →
      `item_interesse`; propriedade `primary_modalidade` → `primary_item`
- [x] 3.2 `whatbot/intent_router.py`: usos de `session.modalidade_interesse`
      → `session.item_interesse` (campo `IntentResult.modalities` já é
      identificador em inglês — mantém o nome, mas revisar se cabe renomear
      para `items` por consistência; decidir na implementação)
- [x] 3.3 `update_session_state` (`whatbot/session_state.py`): assinatura
      muda de `(state, user_message, history, ...)` para receber o
      `IntentResult` (ou `items: List[str]`) já calculado por `route_intent`
      no mesmo turno — remove a chamada própria a
      `facts.match_modalidades(user_message)`/`get_knowledge_facts()` e o
      fallback de varredura das últimas 6 mensagens do histórico
- [x] 3.4 `whatbot/main.py`: ponto de chamada de `update_session_state`
      passa a repassar o `IntentResult` já produzido por `route_intent` no
      mesmo turno, em vez de deixar `update_session_state` recalcular do
      zero

## 4. Demais consumidores

- [x] 4.1 `whatbot/reply_composer.py`: chamadas a `listar_modalidades()` →
      `listar_itens()`; identificadores locais renomeados
- [x] 4.2 `whatbot/claim_validator.py`: identificadores/menções a
      modalidade em validação de reivindicações renomeados
- [x] 4.3 `whatbot/grounding.py`: identificadores/menções a modalidade em
      detecção de alucinação renomeados
- [x] 4.4 `whatbot/fallback.py`: identificadores/menções a modalidade na
      resposta offline renomeados
- [x] 4.5 `whatbot/tools.py`: `buscar_precos(modalidade: str = "")` →
      parâmetro `item` (nome do parâmetro é parte do schema de function
      calling exposto ao Gemini); `listar_modalidades` (tool exposta ao
      modelo) → `listar_itens`; docstrings atualizadas

## 5. Dados e templates

- [x] 5.1 `knowledge/README.md` (template): heading `## Modalidades` →
      `## Itens` e prosa correspondente
- [x] 5.2 Confirmar `knowledge/base.md` (produção): hoje sem seção
      `## Modalidades` (confirmado no `proposal.md`) — nenhuma mudança de
      dado necessária; deploy desta mudança não quebra o KB em produção

## 6. Testes

- [x] 6.1 `tests/kb_fixtures.py`: atualizar as duas fixtures sintéticas
      (heading e campos usados por `CLASS_SCHEDULE_KB` e a fixture sem
      modalidades) para o vocabulário novo
- [x] 6.2 Atualizar suítes existentes que referenciam identificadores
      renomeados: `tests/test_knowledge.py`, `tests/test_grounding.py`,
      `tests/test_domain.py`, `tests/test_fallback.py`,
      `tests/test_main_e2e.py` (ponto que testa `update_session_state`/
      `SessionState`)
- [x] 6.3 Novo teste de regressão de vocabulário
      `tests/test_no_modalidade_leftovers.py`, mesmo padrão de
      `tests/test_no_association_leftovers.py` (scan por glob +
      `Counter` de matches esperados por arquivo) para "modalidade" como
      identificador em `whatbot/**/*.py`, com allowlist para as
      palavras-gatilho de conteúdo em português que continuam de
      propósito (ex.: conjunto de sinônimos em `knowledge_facts.py`,
      mensagens ao cliente que citam a palavra por ela ainda ser um
      sinônimo válido de "item"/"produto" em alguns negócios — decidir
      escopo exato na implementação, documentando cada entrada mantida)
- [x] 6.4 Suíte completa roda sem falhas
      (`python -m unittest discover -s tests -p 'test_*.py'`)

## 7. Sincronização e arquivamento

- [x] 7.1 Conferir que o delta de `specs/conversa/spec.md` deste change
      reflete o que foi implementado de fato (heading, ausência do
      heurístico duplicado)
- [x] 7.2 `openspec archive session-item-tracking-rename`
