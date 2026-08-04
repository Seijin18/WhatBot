# contacts Specification

## Purpose
TBD - created by archiving change contact-interest-memory. Update Purpose after archive.
## Requirements
### Requirement: Estágio do contato transiciona automaticamente

Um contato DEVE poder transicionar automaticamente entre os estágios
`novo_lead`, `interessado` e `comprando` com base em sinais da conversa
(interesse em item do catálogo, intenção de pedido, pedido real do
catálogo). A transição para `cliente_ativo` NÃO DEVE acontecer
automaticamente — exige ação manual de um admin.

#### Scenario: Pedido de catálogo força estágio "comprando"

- **GIVEN** um contato em qualquer estágio anterior a `comprando`
- **WHEN** o contato envia um pedido real pelo catálogo do WhatsApp
- **THEN** o estágio do contato vira `comprando` imediatamente

#### Scenario: Confirmação de cliente ativo é manual

- **GIVEN** um contato no estágio `comprando`
- **WHEN** nenhuma ação de admin confirma a venda
- **THEN** o estágio do contato não avança sozinho para `cliente_ativo`

#### Scenario: Admin confirma cliente ativo

- **GIVEN** um contato identificável por nome ou telefone
- **WHEN** o admin envia um comando confirmando a venda (ex.: "marca a
  Maria como cliente ativo")
- **THEN** o estágio da Maria vira `cliente_ativo`
- **AND** o admin recebe confirmação com o novo estágio

### Requirement: Valor de status é validado contra um conjunto fechado

Qualquer alteração de `contatos.status` DEVE ser validada contra o conjunto
`{"novo_lead", "interessado", "comprando", "cliente_ativo", "cancelado"}`
antes de persistir.

#### Scenario: Valor fora do conjunto é rejeitado

- **WHEN** uma chamada tenta definir `status` com um valor fora do conjunto
  fechado
- **THEN** a operação é rejeitada e o `status` armazenado não muda

