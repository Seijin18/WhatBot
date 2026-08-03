---
description: Explore and refine a broad idea into a structured, gap-covered proposal — no code is written. Chains scope-explorer then planner.
argument-hint: [descrição da ideia ou área a explorar]
allowed-tools: Task, Read, Glob, Grep
model: sonnet
---

Você está no modo de desenvolvimento de ideia. NUNCA use Edit, Write ou Bash
de modificação nesta sessão — o objetivo é sair daqui com uma proposta escrita,
não com código.

Ideia/área recebida: $ARGUMENTS

Execute nesta ordem, sem pular etapas:

1. **Dispare o subagente `scope-explorer`** com a ideia acima. Deixe ele
   mapear o estado atual do projeto, identificar gaps, e sugerir features
   candidatas (núcleo / expansões plausíveis / especulativo).

2. **Apresente a saída do scope-explorer ao usuário e pare.** Pergunte
   explicitamente quais itens da lista (núcleo, expansões, especulativo)
   ele quer levar adiante antes de continuar — não assuma que tudo deve
   virar plano.

3. **Somente após a confirmação do usuário**, dispare o subagente `planner`
   passando os itens confirmados como entrada. O planner deve produzir um
   plano estruturado (arquivos afetados, ordem de implementação, riscos,
   critério de "pronto") para cada item confirmado.

4. **Se houver mais de uma abordagem técnica plausível** para algum item,
   ou se o item for arquiteturalmente sensível (ex: mudança que afeta
   vários módulos do WhatBot — canais, handover, orquestração via Windmill),
   sugira rodar `zen consensus` antes de fechar o plano — não decida sozinho
   em silêncio. Modelos: veja `.claude/ZEN_MODELS.md` — use a faixa
   recomendada por padrão; a faixa premium (ex: opus/o3-pro via OpenRouter)
   só se o usuário pedir explicitamente máximo rigor.

5. **Encerre com um documento único de proposta**, contendo:
   - Resumo da ideia original
   - Gaps identificados e decisão tomada sobre cada um (incluído / adiado / descartado, com motivo)
   - Plano(s) final(is), prontos para revisão
   - Próximo passo sugerido: rodar `/develop` com este plano como entrada

Se em algum ponto o escopo se mostrar grande demais para uma passada só
(ex: repensar toda a arquitetura de canais do WhatBot), pare e sugira dividir
a exploração em sessões por área, em vez de forçar um documento gigante e raso.
