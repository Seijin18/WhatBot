# Revisão aprofundada — camada conversacional do WhatBot

Data: 2026-08-03 · Escopo: `whatbot/` (intenção → conhecimento → prompt → resposta),
com foco em respostas hardcoded, gatilhos que pulam a LLM e redirecionamento errado.

Todas as evidências abaixo foram obtidas executando o código atual (com as
correções já feitas na outra sessão aplicadas) contra a base de conhecimento
real `knowledge/associacao.md` (Camu — ateliê de miniaturas 3D).

---

## Diagnóstico em uma frase

O núcleo conversacional foi escrito **para outro negócio** (associação
esportiva: modalidades, horários, aula experimental, plano mensal/semestral,
matrícula). A base de conhecimento foi trocada para um e-commerce de
colecionáveis 3D, mas a taxonomia de intenções, os templates, o validador
factual e o detector de alucinação continuam presos ao domínio antigo. O
resultado é o sintoma relatado: o bot ora despeja blocos da base, ora
descarta a resposta boa da LLM e a substitui por um texto pré-fabricado que
não tem relação com a pergunta.

---

## P0 — Problemas que impedem uma conversa fluida

### P0.1 — A LLM recebe uma base de conhecimento vazia nas perguntas mais comuns

`whatbot/prompt_builder.py:21` (`_chunks_for_intent`) fatia a base por
intenção e devolve no máximo 3 blocos. Como o KB atual não tem seção
`## Modalidades`, os ramos de `horarios` e o ramo `else` não têm o que
buscar. Prompt real gerado hoje:

| Mensagem do cliente | Intent | Conhecimento entregue à LLM |
|---|---|---|
| `oi` | greeting | só o parágrafo "Sobre" **+ a frase `Nenhuma modalidade cadastrada no momento.`** |
| `o que vocês têm?` | horarios | só o parágrafo "Sobre" |
| `vcs tem instagram?` | unknown | só "Sobre" + `Nenhuma modalidade cadastrada no momento.` |
| `quanto custa?` | precos | Sobre + Preços + Matrícula (ok) |

Ou seja: nas aberturas de conversa (`oi`, `o que vocês têm?`) a LLM **não
recebe o catálogo, nem os preços, nem o FAQ** — e ainda é informada de que
não há nada cadastrado. Ela só pode inventar ou pedir handover. A seção FAQ
nunca entra no prompt, exceto em `intent == faq` (e aí truncada em 2500
chars, `prompt_builder.py:64`).

**Correção:** parar de fatiar. A base inteira tem ~4 KB (≈1k tokens) —
injetar `format_full_context_for_prompt()` sempre. O fatiamento por intenção
só faz sentido com base grande, e aí via recuperação por similaridade, não
por `if intent == ...`. **Nunca** injetar strings de estado vazio
("Nenhuma modalidade cadastrada") como se fossem conhecimento.

### P0.2 — Taxonomia de intenções presa ao domínio esportivo

`whatbot/intent_router.py` só sabe classificar em `greeting | horarios |
precos | experimental | matricula | faq | unknown`. Um e-commerce precisa de
`catálogo`, `pedido/compra`, `prazo/entrega`, `pagamento`, `pós-venda`, e
não tem "horários" nem "aula experimental".

Consequências verificadas:
- `o que vocês têm?` → `INTENT_HORARIOS` (via `_LISTING_SIGNALS`,
  `intent_router.py:25`). Pergunta de catálogo roteada para "horários".
- `INTENT_MATRICULA` existe porque a seção do KB se chama
  `## Matrícula e pagamentos` — que hoje contém "como encomendar".
- `facts.match_modalidades()` sempre devolve `[]` (não há modalidades), então
  `session.modalidade_interesse` nunca é preenchido: **o bot não memoriza
  nada sobre o interesse do cliente**.

### P0.3 — Sinais de intenção poluídos: quase tudo vira "preços"

`knowledge_facts.py:299` (`_build_intent_signals`) extrai **toda palavra com
≥3–4 letras** das seções Preços/FAQ como gatilho. Os sinais de `precos` hoje
incluem: `para`, `com`, `dos`, `uma`, `meu`, `mesmo`, `depende`, `pedido`,
`prazo`, `entrega`, `demora`, `pronto`, `correios`...

Roteamento real medido:

| Mensagem | Intent obtido | Intent correto |
|---|---|---|
| `voces fazem entrega?` | precos | entrega |
| `qual o prazo?` | precos | prazo |
| `como faço pra pagar?` | precos | pagamento |
| `meu cachorro é um golden, da pra fazer?` | precos | qualificação/pedido |
| `quero encomendar` | precos | pedido |

**Correção:** sinais devem vir de palavras-chave declaradas explicitamente
(na própria KB ou num mapa versionado), não de "toda palavra da seção".
Melhor ainda: com a base inteira no prompt, a classificação determinística
deixa de ser necessária para escolher contexto — ela só precisa sobreviver
para o caminho offline.

---

## P1 — Respostas hardcoded e gatilhos que pulam / anulam a LLM

### P1.1 — `ReplyComposer` é um gerador de texto de outra empresa

`whatbot/reply_composer.py` produz literalmente:

- `"Tabela de preços por modalidade:"` (`knowledge.py:301`)
- `"Os planos mensal e semestral valem para ..."`, `"- Plano mensal: R$ X (1 aluno)"`,
  `"Há desconto para o 2º integrante da mesma família"` (`reply_composer.py:156-167`)
- `"A aula experimental de X é agendada para quinta-feira"` + `"envie nome,
  idade, celular/telefone e o dia desejado"` (`reply_composer.py:234`)
- `"Nenhuma modalidade cadastrada no momento."` (`knowledge.py:197`)

Nada disso existe no negócio atual. Esse módulo é alcançado por **três**
caminhos: gatilho de alto risco (P1.2), correção de grounding (P1.3) e
fallback offline (P1.6).

### P1.2 — Gatilho `high_risk_intents` pula a LLM inteira

`main.py:377`:

```python
if intent_result.intent in high_risk_intents():
    composed = get_reply_composer().compose(...)   # response_mode = "template"
```

Quando ativo, **toda** pergunta de preço/experimental nunca chega ao modelo —
é respondida por template. Hoje está inerte por acidente: a outra sessão
passou a exigir a palavra "mensal"/"semestral" na seção Preços
(`knowledge_facts.py:279`), e o KB atual não a tem, então
`high_risk_intents()` é `frozenset()`. **Basta alguém escrever "plano mensal"
na base para o bot voltar a cuspir template em toda pergunta de preço.** É um
gatilho armado, não um problema resolvido.

**Correção:** eliminar a substituição por template. Se um fato é crítico, o
caminho certo é *injetá-lo no prompt com destaque* (e, se necessário,
re-perguntar à LLM), nunca trocar a resposta por texto fixo.

### P1.3 — Detector de alucinação reprova respostas corretas (evidência concreta)

`grounding.py:138` (`detect_hallucination`) marca alucinação quando aparece um
dos marcadores (`temos`, `oferece`, `modalidade`, ...) e alguma palavra com
≥5 letras não é **substring literal** do texto da base.

Caso real medido:

```
CLIENTE: o que vocês têm?
LLM....: "Temos miniaturas personalizadas do seu pet, nos tamanhos mini (9cm)
          e padrão (12cm), e também o Pato de Tricô. Qual te interessou?"
→ detect_hallucination = True   (a base diz "tamanho", a resposta diz "tamanhos")
→ ENVIADO AO CLIENTE: "Nenhuma modalidade cadastrada no momento.
                       Se precisar de mais alguma coisa, é só me chamar."
```

Uma resposta perfeita, 100% ancorada, é trocada por uma mensagem de sistema
absurda — só porque um plural não bate letra a letra. E `temos` é uma das
palavras mais comuns do português, então o gatilho dispara o tempo todo.

**Correção:** validar **fatos citados** (valores `R$`, números, nomes
próprios, prazos), não vocabulário. E quando reprovar, o comportamento certo
é *repromptar a LLM apontando o erro*, com o template como último recurso
absoluto — nunca como primeira alternativa.

### P1.4 — FAQ devolve a pergunta errada, com o rótulo colado

`knowledge.py:352` (`buscar_faq`) pontua por substring de token
(`token in key`), então tokens como `o`, `de`, `um` casam com qualquer
pergunta. E devolve `"P: <pergunta>\nR: <resposta>"`; quem consome apenas
remove os rótulos, deixando a pergunta como cabeçalho.

Medido:

| Cliente perguntou | Bot responderia |
|---|---|
| `vcs tem instagram?` | `"quanto tempo demora para ficar pronto?\n Até 5 dias úteis..."` |
| `quais os horarios?` | `"quais fotos preciso mandar do meu pet?\n 2 a 3 fotos..."` |

Isto é exatamente o "bot que cospe informação": ele repete uma pergunta do
FAQ como se fosse dele e responde outra coisa. Ironicamente, a regra 5 do
próprio prompt manda a LLM *não* fazer isso (`knowledge.py:230`) — mas os
caminhos determinísticos fazem.

`buscar_faq` também **nunca admite desconhecimento**: sempre devolve o melhor
palpite ou a lista inteira de perguntas.

### P1.5 — Guarda de tamanho que devolve o que acabou de rejeitar

`grounding.py:232`:

```python
if not body or len(body) > _MAX_GROUNDED_REPLY_LEN:
    return composed        # ← o `composed` foi descartado 40 linhas acima
```                        #    justamente por passar de 1200 chars

O limite de 1200 chars não protege nada nesse ramo.

### P1.6 — Fallback offline despeja a base inteira com texto da associação

`fallback.py:63` (`wrap_fallback_reply`) envia:

> "No momento estou com instabilidade, mas consegui estas informações
> **oficiais da associação**: [tabela completa de preços + matrícula +
> pagamentos] Digite *quero falar com a **secretaria*** se precisar de ajuda
> humana."

Medido: para `voces fazem entrega?`, `qual o prazo?` e `quero encomendar` o
fallback devolve **a mesma parede de texto de preços** (porque os sinais de
"precos" casam com tudo — P0.3). Para `oi tudo bem?`, devolve
`"Nenhuma modalidade cadastrada no momento."`.

### P1.7 — `ClaimValidator` com regras de outro negócio, armadas

`claim_validator.py` valida "dia da aula experimental", "preço de
experimental", "R$ X é plano mensal". `_strip_boilerplate` procura a string
literal `"se quiser agendar aula experimental"`. Hoje inerte (`monthly_price
is None`); volta a reprovar respostas corretas assim que a base mencionar
planos — a regra `price_missing_plan_context` (`claim_validator.py:127`)
exige que qualquer resposta com valor cite "mensal/semestral/plano/tabela".

### P1.8 — Textos fixos remanescentes do domínio antigo

| Arquivo | Texto |
|---|---|
| `main.py:67` | `"...digite *quero falar com a secretaria*..."` |
| `domain.py:18-35` | lista de handover só reconhece "secretaria"/"atendente" |
| `domain.py:57,60` | `"nossa secretaria dará continuidade"` |
| `fallback.py:69,72` | `"informações oficiais da associação"` / `"secretaria"` |
| `priority.py:5-22` | lead quente = `matricula`, `vaga`, `aula experimental` (nunca `encomendar`, `comprar`, `pedido`) |
| `admin.py:54,57` | `#simular ... Olá, quero judô` e **telefone `5511949305094` hardcoded** |
| `session_state.py:88` | tópico `"aula experimental"` |
| `knowledge.py:229` | regra de prompt `"sem emojis"` fixa; regra 2 diz `"consulte a seção de modalidades abaixo"` — seção que não existe |
| `reply_composer.py` | `association_name` = `"Camu (@camu3d)"` vira `"Somos a Camu (@camu3d)"` ao cliente (o handle não deveria entrar na fala) |

---

## P2 — Estrutura, estado e rede de segurança

### P2.1 — Não existe estado de pedido

`SessionState` (`session_state.py:26`) guarda apenas
`modalidade_interesse`, `topico_atual`, `aguardando_dados_experimental`. Para
este negócio o bot precisaria lembrar: item, tamanho (9/12cm), acabamento
(cor única/kit), 1 ou 2 pets, fotos recebidas, endereço/frete. Como
`match_modalidades()` devolve `[]`, hoje **nenhum dos três campos é
preenchido** — a sessão é inerte.

`whatbot/booking_flow.py` é **código morto** (nenhum import em todo o repo)
e também modela o funil de aula experimental.

### P2.2 — Contexto curto e resumo enviesado

`main.py:354` carrega 6 mensagens (3 turnos). `history_summary()`
(`session_state.py:75`) só sabe rotular "preços", "horários" e "aula
experimental" — num negócio sob encomenda, o resumo do histórico é
praticamente sempre vazio ou errado.

### P2.3 — Token de handover pode vazar

`detectar_intencao_human_handoff` (`domain.py:39`) só casa `[HUMAN_HANDOVER]`
exato. Se o modelo escrever `HUMAN_HANDOVER` sem colchetes ou variar o
formato, o token não é detectado **e vai literalmente para o cliente** — o
caminho normal de envio (`main.py:524`) não chama `strip_handover_token()`.

### P2.4 — 20 testes quebrados: nenhuma rede de segurança na camada conversacional

`python -m unittest discover -s tests -p 'test_*.py'` → **63 testes, 20
falhas reais**, todas em `test_grounding` (10), `test_knowledge` (9) e
`test_domain` (1). Motivo: a suíte lê `knowledge/associacao.md` **de
produção** e afirma coisas como `assertEqual(facts.monthly_price, 150)` e
`assertIn("yoga", base.modalidades)`.

(Há mais 16 erros de import por `psycopg` ausente no venv local — problema de
ambiente, não de código.)

**Correção:** a suíte precisa de fixtures próprias em `tests/` — no mínimo
duas bases (uma de serviço com agenda, uma de produto/catálogo) — e nenhum
teste deve depender do conteúdo do KB de produção. Sem isso, qualquer
correção aqui é feita às cegas.

### P2.5 — A capability conversacional não tem spec

`openspec/specs/` só tem `channels/`. Todo o ciclo intenção → conhecimento →
prompt → validação → resposta nunca foi especificado — foi exatamente por
isso que ele derivou junto com o negócio antigo e ninguém percebeu.

---

## Plano de correção sugerido (ordem de dependência)

### Fase 1 — Destravar a conversa (maior ganho, menor risco)
1. `prompt_builder`: injetar a base completa no system prompt; remover o
   fatiamento por intenção e qualquer string de estado vazio.
2. `knowledge.format_grounding_rules_for_prompt`: derivar as regras das
   seções que a base **tem**, sem citar "modalidades"; tirar o "sem emojis"
   fixo; instruir explicitamente o "não sei + oferecer handover".
3. Remover o gatilho `high_risk_intents` → template em `main.py:377`.

### Fase 2 — Desarmar o que anula a LLM
4. Reescrever `detect_hallucination` para checar **fatos citados** (valores,
   números, nomes próprios) em vez de vocabulário token-a-token.
5. Em caso de reprovação, **repromptar a LLM** com o motivo; template só como
   último recurso, e nunca com texto de outro domínio.
6. `ClaimValidator`: regras derivadas de restrições declaradas na base, não
   de "mensal/semestral/experimental".
7. Corrigir a guarda de tamanho em `grounding.build_knowledge_reply`.

### Fase 3 — Tirar o domínio antigo do código
8. Generalizar o parser da KB: qualquer `## Seção` com `### Itens` vira
   catálogo (hoje só `## Modalidades`); renomear/mapear
   `Matrícula e pagamentos` → `Como comprar`.
9. Substituir os sinais de intenção auto-extraídos por um mapa declarado;
   renomear intents para o vocabulário do negócio.
10. Mover os textos fixos de sistema (handover, indisponibilidade,
    encerramento, prioridade) para a KB ou config, com placeholders.
11. Limpar `priority.py`, `domain.py` (keywords de handover), `admin.py`
    (telefone e exemplo hardcoded).

### Fase 4 — Estado, testes e spec
12. `SessionState` orientado a pedido, com slots declarados na base;
    remover ou reaproveitar `booking_flow.py`.
13. Fixtures de KB em `tests/`, desacoplando a suíte do KB de produção; e
    estender `tests/test_main_e2e.py` conforme a convenção do projeto.
14. Criar a spec OpenSpec da capability conversacional
    (`openspec/specs/conversa/`), fixando: "nenhuma resposta ao cliente pode
    ser texto fixo de domínio", "a base completa vai ao prompt", "correção de
    grounding é reprompt, não substituição".

---

## Já corrigido na outra sessão (não refazer)

- `knowledge_facts._parse_prices` só assume mensal/semestral quando a seção
  fala em planos — o que desarmou (por ora) `high_risk_intents`.
- `default_closing()` adaptativo em vez de `_CLOSING` fixo com "aula
  experimental".
- `_compose_greeting` com variante para negócio sem modalidades.
- `detect_hallucination` restrito à parte estruturada (lista) da resposta —
  mitigação parcial; o falso-positivo do P1.3 continua acontecendo quando a
  resposta não tem lista.
- `SYSTEM_PROMPTS` e `DEFAULT_CASUAL_TEST_MESSAGE` neutralizados.

---

## Implementado nesta sessão (2026-08-04)

Fases 1–4 do plano acima, nesta ordem: P0.1/P1.2/P1.8 (base completa no
prompt, remoção do gatilho de template, cabeçalhos de seção derivados do
arquivo), P1.3/P1.5 (falso-positivo de alucinação em resposta sem lista,
guard de tamanho quebrado), P0.2/P0.3 (sinais de intenção curados, intents
`pagamento`/`entrega` novos), P1.4 (`buscar_faq` reescrito), P1.1/P2.1
(degradação graciosa para negócio sem modalidades), textos fixos
generalizados (`main.py`, `domain.py`, `fallback.py`, `admin.py`,
`priority.py`, `tools.py`), `booking_flow.py` removido (código morto),
suíte desacoplada do KB de produção (`tests/kb_fixtures.py` — duas bases
sintéticas), spec OpenSpec criada (`openspec/specs/conversa/spec.md`).

Detalhe de cada correção nos commits/diffs; ver os comentários inline nos
arquivos alterados, que citam este documento.

### P1.9 — `_ORG_CLAIM` casava com quase qualquer frase "o/a X é ..." (achado tardio, maior impacto que os anteriores)

Descoberto numa simulação final de sanidade do pipeline completo, depois de
todas as outras correções — não estava no escopo original porque só se
manifesta em respostas de prosa comuns, não nos casos sintéticos
inicialmente testados.

`grounding.py`, regex `_ORG_CLAIM` (usada em `detect_hallucination` para
achar reivindicação fabricada de identidade, ex.: `"O TimeVivo é uma
associação..."`) não exigia que o trecho capturado parecesse um nome
próprio — casava com **qualquer** "o/a `<substantivo comum>` é":

```
"O prazo é de até 5 dias úteis."        -> capturou "prazo"
"A entrega é feita pelos Correios."     -> capturou "entrega"
"O pagamento é feito via Pix."          -> capturou "pagamento"
"O frete é calculado por pedido."       -> capturou "frete"
```

Como nenhuma dessas palavras aparece *sozinha* no blob normalizado da base
do jeito exato que o check requer, cada uma disparava `detect_hallucination
= True` — e a resposta, mesmo perfeita, era substituída. Diferente do
P1.3 (que só afeta respostas sem lista com uma palavra específica fora da
base), esse regex roda em **toda** resposta do caminho principal
(`ensure_grounded_reply` é chamado em todo turno não-fallback) e "o/a X é"
é uma das construções mais comuns do português — provavelmente a fonte de
falso-positivo mais frequente da alucinação em produção antes desta
correção.

**Correção:** exigir que o trecho capturado comece com maiúscula (heurística
de nome próprio), mantendo os artigos/verbo case-insensitive via grupo
`(?i:...)` escopado — sem essa distinção, remover `re.I` global também
quebraria o caso legítimo (`"O TimeVivo é..."`). Validado contra 12 frases
(6 falso-positivo antigo, 1 caso legítimo, 5 variações) e contra a suíte
completa com dependências reais (281 testes, 0 falhas).
