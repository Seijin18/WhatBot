# Delta: admin

## ADDED Requirements

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
