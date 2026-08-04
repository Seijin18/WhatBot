# conversa Specification

## Purpose
TBD - created by archiving change conversational-layer-hardening. Update Purpose after archive.
## Requirements
### Requirement: Base de conhecimento completa no prompt

O prompt de sistema enviado à LLM DEVE incluir a base de conhecimento
completa (`KnowledgeStore.format_full_context_for_prompt()`), independente
da intenção detectada na mensagem do cliente. Nenhum recorte por intenção
DEVE omitir seções da base do prompt.

#### Scenario: Saudação recebe o catálogo completo

- **WHEN** o cliente envia uma saudação ("oi") ou mensagem fora do roteiro
- **THEN** o prompt de sistema contém preços, FAQ e todas as seções da base
- **AND** nenhum marcador de estado vazio (ex.: "nenhuma modalidade
  cadastrada") aparece no prompt quando a base tem conteúdo em outras seções

#### Scenario: Base pequena não é fatiada por intenção

- **WHEN** o contexto é montado para qualquer intenção detectada
- **THEN** o contexto é idêntico ao dump completo da base
  (`build_context_for_intent(...) == format_full_context_for_prompt()`)

### Requirement: Nenhuma intenção substitui a resposta da LLM antes de gerá-la

O sistema NÃO DEVE decidir, antes de chamar o modelo, que uma intenção é
"de alto risco" e responder com um template fixo em vez de gerar a resposta.
Toda mensagem de cliente DEVE passar pela LLM primeiro; correção factual
acontece somente depois, sobre o texto já gerado.

#### Scenario: Pergunta de preço sempre chama o modelo

- **WHEN** o cliente pergunta sobre preço, prazo ou qualquer outro tópico
  coberto pela base
- **THEN** a LLM é chamada para gerar a resposta
- **AND** nenhum código de intenção provoca substituição por template antes
  da chamada ao modelo

### Requirement: Grounding valida fatos citados, não vocabulário livre

A detecção de alucinação e a validação de reivindicações DEVEM operar sobre
fatos verificáveis citados na resposta (valores monetários, números, nomes
próprios, dias da semana) — não sobre a presença de palavras específicas do
vocabulário da base. Uma resposta sem reivindicação factual verificável
NÃO DEVE ser reprovada por reformular palavras da base (plural, sinônimo,
conectivo).

#### Scenario: Reformulação correta não é reprovada

- **WHEN** a resposta da LLM reformula um fato da base corretamente (ex.:
  usa o plural de uma palavra que na base está no singular)
- **THEN** a resposta não é classificada como alucinação

#### Scenario: Fato inventado em lista é reprovado

- **WHEN** a resposta lista um item, preço ou nome que não existe na base
- **THEN** a resposta é classificada como alucinação e substituída por uma
  resposta ancorada na base

#### Scenario: Correção nunca devolve o texto já rejeitado

- **WHEN** a tentativa de montar uma resposta curta ancorada na base falha
  (vazia ou longa demais)
- **THEN** o chamador recebe um sinal explícito de "sem alternativa" e
  preserva a resposta original da LLM, em vez de reenviar o texto já
  descartado por exceder o limite

### Requirement: Rótulos de seção vêm do arquivo de conhecimento

Qualquer cabeçalho de seção citado no prompt ou numa resposta ao cliente
DEVE vir do texto do próprio arquivo de conhecimento (`## <Seção>` como
escrito), nunca de uma tradução fixa no código.

#### Scenario: Seção com nome de negócio diferente do original

- **WHEN** o arquivo de conhecimento renomeia uma seção padrão (ex.:
  "Matrícula e pagamentos" vira algo específico do negócio)
- **THEN** o texto exibido ao cliente ou à LLM usa o cabeçalho real do
  arquivo, não uma string fixa no código

### Requirement: Intenção não fica presa a vocabulário de um único negócio

O roteamento de intenção DEVE derivar sinais de um vocabulário curado
válido para qualquer pequeno negócio (preço, pagamento, entrega/prazo,
pedido, horário), não apenas do domínio de aulas com horário fixo. Uma
seção de conteúdo correspondente a uma intenção NÃO DEVE ter todo o seu
texto livre (não estruturado) despejado como sinal de gatilho.

#### Scenario: Pergunta de entrega não vira pergunta de preço

- **WHEN** o cliente pergunta sobre prazo, frete ou entrega
- **THEN** a intenção detectada é de entrega, não de preço

#### Scenario: Pergunta de pagamento é reconhecida

- **WHEN** o cliente pergunta como pagar (pix, cartão, parcelamento)
- **THEN** a intenção detectada é de pagamento

### Requirement: FAQ nunca inventa correspondência

A busca de FAQ DEVE admitir explicitamente que não encontrou uma pergunta
correspondente quando a sobreposição de palavras de conteúdo entre a
pergunta do cliente e as perguntas cadastradas for nula. Uma pergunta do
FAQ NÃO DEVE ser retornada como resposta a uma pergunta de tópico
completamente diferente só por compartilhar palavras genéricas (pronomes,
verbos auxiliares, artigos).

#### Scenario: Pergunta sem correspondência real admite desconhecimento

- **WHEN** a pergunta do cliente não compartilha nenhuma palavra de
  conteúdo com nenhuma pergunta do FAQ
- **THEN** a busca retorna que não encontrou, e não a pergunta/resposta
  mais parecida por acaso

### Requirement: Mensagens fixas ao cliente são genéricas quanto ao negócio

Textos fixos enviados ao cliente pelo sistema (indisponibilidade de
modelo, encaminhamento para atendimento humano, fallback offline) NÃO
DEVEM presumir um tipo de negócio específico (ex.: citar "secretaria" ou
"associação" incondicionalmente) — devem funcionar para qualquer negócio
atendido pelo bot.

#### Scenario: Encaminhamento para humano é genérico

- **WHEN** o sistema encaminha o cliente para atendimento humano, por
  pedido do cliente ou decisão do modelo
- **THEN** a mensagem ao cliente não presume um tipo específico de negócio
  ou cargo (ex.: não força "secretaria" incondicionalmente)

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

