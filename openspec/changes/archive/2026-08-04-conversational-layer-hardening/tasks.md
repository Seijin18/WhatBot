## 1. Prompt e gatilhos que puliam a LLM

- [x] 1.1 `prompt_builder.py`: parar de fatiar por intenção, sempre injetar
      `format_full_context_for_prompt()`
- [x] 1.2 `knowledge.py`: remover cabeçalhos de seção incondicionais sem
      conteúdo (ex.: "MODALIDADES CADASTRADAS" vazio) e generalizar
      `format_grounding_rules_for_prompt()`
- [x] 1.3 `main.py`: remover o gatilho `high_risk_intents` → template que
      substituía a resposta antes de chamar o modelo

## 2. Grounding e validação factual

- [x] 2.1 `grounding.py`: corrigir falso-positivo de alucinação em resposta
      sem lista (fallback que escaneava a resposta inteira)
- [x] 2.2 `grounding.py`: tolerância a plural/singular simples na checagem
      de token conhecido
- [x] 2.3 `grounding.py`: corrigir guard de tamanho que devolvia a mesma
      resposta já rejeitada por ser longa demais

## 3. Roteamento de intenção e FAQ

- [x] 3.1 `knowledge_facts.py`: substituir "toda palavra da seção" por
      vocabulário curado; adicionar intents `pagamento`/`entrega`
- [x] 3.2 `knowledge_facts.py`: filtrar palavras genéricas mineradas de
      perguntas do FAQ (evitar contaminação cruzada de intenção)
- [x] 3.3 `knowledge.py`: reescrever `buscar_faq` com sobreposição de
      palavras de conteúdo (não substring de token curto) e admissão
      explícita de "não encontrei"

## 4. Degradação graciosa sem modalidades

- [x] 4.1 `knowledge.py`: `titulo_secao()` deriva rótulos do cabeçalho real
      do arquivo, não de tradução fixa
- [x] 4.2 `knowledge.py`: `listar_modalidades()`/`buscar_precos()` caem para
      o catálogo de preços quando não há seção de modalidades
- [x] 4.3 `reply_composer.py`: `_compose_horarios` não tenta buscar horário
      de modalidade inexistente

## 5. Textos fixos e dados hardcoded

- [x] 5.1 Generalizar mensagens fixas ao cliente (`main.py`, `fallback.py`,
      `domain.py`, `knowledge.py`) — remover presunção de "secretaria"/
      "associação"
- [x] 5.2 `priority.py`: adicionar vocabulário de pedido/compra à detecção
      de lead quente
- [x] 5.3 `admin.py`: telefone da linha WhatsApp Business lido de
      `ASSOCIATION_PHONE`, não hardcoded; exemplo de teste genérico
- [x] 5.4 `tools.py`: docstrings das tools (expostas à LLM em function
      calling) generalizadas
- [x] 5.5 Remover `whatbot/booking_flow.py` (código morto)

## 6. Testes

- [x] 6.1 `tests/kb_fixtures.py`: duas bases sintéticas (turmas com horário
      + catálogo sem modalidades), carregadas via `reload_from_text` no
      singleton do `KnowledgeStore`
- [x] 6.2 Reescrever `tests/test_knowledge.py`, `tests/test_domain.py`,
      `tests/test_grounding.py` para usar as fixtures em vez de
      `knowledge/associacao.md`
- [x] 6.3 Corrigir dependência implícita de ordem de execução (testes que
      liam o singleton global sem `setUp` próprio)
- [x] 6.4 Suíte completa roda sem falhas (`python -m unittest discover`)
