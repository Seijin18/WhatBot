# Delta: contacts

## ADDED Requirements

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
