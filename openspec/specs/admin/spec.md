# admin Specification

## Purpose
TBD - created by archiving change handover-summary-for-agent. Update Purpose after archive.
## Requirements
### Requirement: Notificação de handover inclui resumo do contato

Toda notificação de novo contato na fila DEVE incluir um resumo curto do
estágio e do interesse do contato, além dos dados já exibidos (nome, canal,
prioridade). Quando o handover foi disparado por um pedido do catálogo, o
resumo DEVE indicar se os itens do pedido são identificáveis e, quando não
forem, DEVE avisar explicitamente o atendente para confirmar com o cliente.

#### Scenario: Contato com interesse registrado

- **WHEN** um contato com item de interesse registrado entra na fila
- **THEN** a notificação ao admin inclui esse item no resumo

#### Scenario: Pedido do catálogo com itens identificáveis

- **WHEN** o handover foi disparado por um pedido do catálogo com itens
  identificáveis
- **THEN** o resumo lista os itens do pedido
- **AND** cada item mostra a quantidade pedida quando maior que 1 (ex.:
  "Boné x3"), para que o atendente saiba exatamente quanto entregar/cobrar

#### Scenario: Resolução parcial dos itens do pedido

- **WHEN** o pedido tem itens identificáveis, mas o catálogo local só
  resolve nome/preço para parte deles (`catalog-product-sync` sem cache
  para os demais `productId`)
- **THEN** o resumo lista os itens resolvidos normalmente
- **AND** sinaliza explicitamente quantos itens do pedido não puderam ser
  identificados, em vez de mostrar o pedido como se fosse só os itens
  resolvidos

#### Scenario: Pedido do catálogo sem itens identificáveis

- **WHEN** o handover foi disparado por um pedido do catálogo sem itens
  identificáveis
- **THEN** o resumo avisa explicitamente que os itens não puderam ser
  identificados e que o atendente deve confirmar com o cliente

#### Scenario: Contato sem nenhum sinal de interesse

- **WHEN** um contato sem nenhum interesse registrado entra na fila (ex.:
  handover pedido diretamente pelo cliente sem contexto prévio)
- **THEN** a notificação continua sendo enviada normalmente, sem uma seção
  de resumo vazia ou quebrada

### Requirement: Admin pausa o bot de um contato específico

Um admin DEVE poder desativar o bot (`ia_ativa = FALSE`) para qualquer
contato através de um comando em linguagem natural, independente de o
contato estar na fila de atendimento. A pausa DEVE ser indefinida — o bot
NÃO DEVE ser reativado automaticamente por prazo, só por um comando
explícito de reativação.

#### Scenario: Pausar contato fora da fila

- **GIVEN** um contato com `ia_ativa = TRUE` que não está na fila de
  atendimento
- **WHEN** o admin envia "pausa o bot para o João"
- **THEN** `ia_ativa` do João vira `FALSE`
- **AND** o admin recebe confirmação indicando como reativar

#### Scenario: Contato pausado não é reativado automaticamente

- **GIVEN** um contato pausado por este comando (não por handover)
- **WHEN** a rotina periódica de reativação automática roda
  (`process_auto_reactivations`)
- **THEN** o contato continua com `ia_ativa = FALSE`
- **AND** só volta a `TRUE` quando o admin enviar um comando explícito de
  reativação

#### Scenario: Comando de reativação existente também retoma pausa manual

- **GIVEN** um contato pausado pelo comando deste requisito
- **WHEN** o admin envia "libera o bot para o João"
- **THEN** `ia_ativa` do João volta a `TRUE`

#### Scenario: Pausar contato já pausado é idempotente

- **GIVEN** um contato com `ia_ativa = FALSE`
- **WHEN** o admin tenta pausá-lo de novo
- **THEN** o bot informa que o contato já está com o bot pausado, sem erro

#### Scenario: Nome ambíguo desambigua antes de pausar

- **GIVEN** mais de um contato ativo correspondendo ao nome informado
- **WHEN** o admin envia o comando de pausa
- **THEN** o bot pergunta qual contato, no mesmo formato de desambiguação
  usado pelos demais comandos de admin
- **AND** nenhum contato é pausado até a resposta

