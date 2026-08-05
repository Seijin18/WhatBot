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

### Requirement: Contato tem tipo de cliente

Todo contato DEVE ter um campo `tipo_cliente` com valor `"b2c"` ou
`"b2b"`. Contatos novos e contatos existentes migrados DEVEM assumir
`"b2c"` como valor padrão. Um admin DEVE poder alterar o `tipo_cliente` de
qualquer contato através de um comando em linguagem natural.

#### Scenario: Contato novo nasce como B2C

- **WHEN** um contato é criado pelo fluxo normal de atendimento (primeira
  mensagem de um número novo)
- **THEN** `tipo_cliente` é `"b2c"`

#### Scenario: Migração de base existente

- **WHEN** a migração roda sobre contatos criados antes deste change
- **THEN** todo contato existente fica com `tipo_cliente = "b2c"`
- **AND** rodar a migração de novo não altera mais nada

#### Scenario: Admin marca contato como empresa

- **GIVEN** um contato identificável por nome ou telefone
- **WHEN** o admin envia "marca a Maria como empresa"
- **THEN** o `tipo_cliente` da Maria vira `"b2b"`
- **AND** o admin recebe confirmação com o novo tipo

#### Scenario: Nome ambíguo desambigua antes de alterar

- **GIVEN** mais de um contato correspondendo ao nome informado
- **WHEN** o admin envia o comando de marcação
- **THEN** o bot pergunta qual contato, no mesmo formato de desambiguação
  já usado por outros comandos de admin
- **AND** nenhum `tipo_cliente` é alterado até a resposta

