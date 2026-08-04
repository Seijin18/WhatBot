## MODIFIED Requirements

### Requirement: Degradação graciosa sem conceito de itens

Um negócio cujo arquivo de conhecimento não tem seção `## Itens` (catálogo
de produtos, não turmas com horário) DEVE receber respostas coerentes nos
mesmos fluxos que um negócio com itens cadastrados usa — nenhum caminho
DEVE responder com uma mensagem de estado vazio ("nenhum item cadastrado")
como se fosse uma resposta válida ao cliente.

O esquema de conhecimento (heading da seção, nome da classe/campo que
representa um item cadastrado, texto injetado no prompt da LLM) DEVE usar
vocabulário neutro de negócio — não um termo específico de um tipo de
negócio (ex.: associação esportiva) —, para que qualquer negócio que reuse
este código encontre um esquema que já fala a língua dele.

#### Scenario: "O que vocês têm?" sem itens cadastrados

- **WHEN** o cliente pergunta o que a empresa oferece e a base não tem
  seção de itens
- **THEN** a resposta mostra o catálogo/tabela de preços real da base

#### Scenario: Heading da seção usa vocabulário neutro

- **WHEN** um arquivo de conhecimento cadastra itens (`## Itens`)
- **THEN** o parser reconhece a seção e qualquer texto exibido ao cliente
  ou injetado no prompt usa "item"/"itens", não um termo de domínio
  específico como "modalidade"

## ADDED Requirements

### Requirement: Rastreio de interesse deriva de um único evento estruturado

O interesse do cliente em item(ns) rastreado entre turnos
(`SessionState.item_interesse`) DEVE derivar do mesmo evento estruturado
que já decide a intenção do turno (`IntentResult`, calculado por
`route_intent`), não de uma heurística de texto paralela que reprocessa a
mensagem e o histórico de forma independente. Não DEVE existir mais de um
caminho de código que decida, no mesmo turno, quais itens o cliente
demonstrou interesse — os dois podem divergir e o rastreio de sessão perde
sentido como memória confiável.

#### Scenario: Intenção e sessão não divergem no mesmo turno

- **WHEN** o roteador de intenção calcula os itens mencionados na mensagem
  do turno atual
- **THEN** a atualização de `SessionState.item_interesse` para o mesmo
  turno usa exatamente esse resultado, sem recalcular por conta própria

#### Scenario: Nenhuma varredura de histórico paralela

- **WHEN** a mensagem do turno atual não menciona nenhum item
  reconhecível
- **THEN** a atualização de sessão não varre mensagens anteriores do
  histórico buscando um item por conta própria — o interesse da sessão só
  muda quando o roteador de intenção do turno atual produz um item
