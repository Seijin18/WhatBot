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

### Requirement: Finalizar atendimento reativa o bot imediatamente

Quando um atendimento é finalizado — comando "atendi o X" (item único),
finalização em lote, ou resposta direta da secretaria via WhatsApp
Business — o bot DEVE voltar a responder o contato imediatamente
(`ia_ativa = TRUE`, `bot_resume_at = NULL`), sem prazo de espera. Não
DEVE haver janela em que o contato fica sem bot e sem atendimento humano
assumido.

#### Scenario: Finalizar um item da fila reativa o bot na hora

- **GIVEN** um contato na fila de atendimento
- **WHEN** o admin envia "atendi o João" (ação `complete`)
- **THEN** `ia_ativa` do João volta a `TRUE` imediatamente
- **AND** `bot_resume_at` fica `NULL`
- **AND** a confirmação ao admin não menciona um prazo de reativação

#### Scenario: Finalização em lote reativa todos os contatos na hora

- **GIVEN** múltiplos contatos na fila de atendimento
- **WHEN** o admin finaliza todos em lote
- **THEN** cada contato finalizado volta com `ia_ativa = TRUE` e
  `bot_resume_at = NULL` imediatamente

#### Scenario: Secretaria responde via WhatsApp Business reativa o bot na hora

- **GIVEN** um contato na fila de atendimento
- **WHEN** a secretaria responde esse contato diretamente pelo WhatsApp
  Business (auto-completar via `handle_staff_outgoing_message`)
- **THEN** o contato sai da fila com `ia_ativa = TRUE` e
  `bot_resume_at = NULL` imediatamente, sem prazo de espera

### Requirement: Simular como o próprio admin usa o fluxo real

Quando o admin usa `#simular` (sessão persistente ou de um turno só) com o
número simulado igual ao próprio número do admin, o sistema DEVE processar
a mensagem pelo fluxo real de cliente — persistindo em `mensagens` e
`session_state`, e enviando a resposta de verdade pelo canal — em vez do
sandbox que não persiste nada. Simular como qualquer outro número DEVE
continuar sandboxed, sem tocar dados reais.

#### Scenario: Simular como o próprio número persiste e responde de verdade

- **WHEN** o admin simula como cliente usando o próprio número
- **THEN** a mensagem do turno é salva no histórico do contato
- **AND** a resposta do bot é enviada de verdade pelo canal, não apenas
  decorada e mandada de volta ao admin

#### Scenario: Simular como outro número continua sandboxed

- **WHEN** o admin simula como cliente usando um número diferente do
  próprio
- **THEN** nada é persistido no histórico real desse outro contato
- **AND** a resposta continua sendo apenas decorada e enviada ao admin,
  nunca ao número simulado

