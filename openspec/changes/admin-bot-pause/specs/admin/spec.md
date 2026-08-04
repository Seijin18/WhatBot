# Delta: admin

## ADDED Requirements

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
