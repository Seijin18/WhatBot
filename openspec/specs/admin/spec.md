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
explícito de reativação (ou por "ativar", ver abaixo). Resolver o alvo por
telefone direto (um único telefone ou uma lista separada por vírgula) DEVE
ser tão idempotente quanto resolver por nome — repetir o comando para um
contato já pausado NÃO DEVE mutar o banco de novo.

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

#### Scenario: Pausar por telefone direto já pausado é idempotente

- **GIVEN** um contato com `ia_ativa = FALSE`, identificado só pelo
  telefone (sem nome resolvível)
- **WHEN** o admin envia "desativa o bot 5511999999999"
- **THEN** o bot responde que o contato já está pausado
- **AND** nenhum `UPDATE` é executado

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

### Requirement: Admin ativa o bot com o verbo "ativar"

O comando de reativação DEVE reconhecer "ativar"/"ativa" acompanhado da
palavra "bot" como sinônimo de "reativar", sem colidir com o comando de
pausa ("desativar").

#### Scenario: "Ativa o bot" reativa

- **GIVEN** um contato com `ia_ativa = FALSE`
- **WHEN** o admin envia "ativa o bot 5511999999999"
- **THEN** `ia_ativa` do contato vira `TRUE`

#### Scenario: "Desativa o bot" continua pausando, não reativando

- **GIVEN** um contato com `ia_ativa = TRUE`
- **WHEN** o admin envia "desativa o bot 5511999999999"
- **THEN** o bot pausa o contato (ação `pause`), NÃO reativa

### Requirement: Ativar/desativar uma lista de telefones

Um admin DEVE poder ativar ou desativar o bot para vários telefones de uma
vez, separados por vírgula, numa única mensagem.

#### Scenario: Lista com estados mistos

- **GIVEN** dois contatos existentes, um com `ia_ativa = TRUE` e outro com
  `ia_ativa = FALSE`
- **WHEN** o admin envia "desativa o bot 5511111111111, 5511222222222"
  (o primeiro ativo, o segundo já pausado)
- **THEN** o bot responde com um resumo agrupado: o primeiro telefone na
  seção "pausado agora", o segundo na seção "já estava pausado"
- **AND** só o primeiro contato sofre mutação no banco

#### Scenario: Lista com telefone inexistente

- **GIVEN** uma lista onde um dos telefones não corresponde a nenhum
  contato
- **WHEN** o admin envia o comando de ativar/desativar com essa lista
- **THEN** o telefone inexistente aparece na seção "não encontrado" da
  resposta
- **AND** o bot NÃO inicia um fluxo de criação de contato para ele (isso
  só acontece com telefone único, ver requirement abaixo)

#### Scenario: Telefone duplicado na lista

- **GIVEN** o mesmo telefone informado duas vezes na lista
- **WHEN** o admin envia o comando
- **THEN** o telefone aparece uma única vez na resposta e sofre no máximo
  uma mutação

### Requirement: Oferecer criar contato ao não encontrar telefone único

Quando um comando de ativar/desativar informa um único telefone (sem
vírgula) que não corresponde a nenhum contato, o bot DEVE oferecer
cadastrá-lo como novo contato antes de simplesmente informar "não
encontrado".

#### Scenario: Admin aceita criar o contato

- **GIVEN** um telefone sem contato correspondente
- **WHEN** o admin envia "desativa o bot 5511000000000"
- **THEN** o bot pergunta se deve cadastrar o número como novo contato e
  pede o nome
- **WHEN** o admin responde com um nome
- **THEN** um contato é criado com esse `push_name`, o telefone informado
  e `ia_ativa` já no estado pedido originalmente (pausado, no exemplo)

#### Scenario: Admin recusa criar o contato

- **GIVEN** o bot perguntou se deve criar o contato
- **WHEN** o admin responde "não" (ou "n"/"cancelar")
- **THEN** nenhum contato é criado
- **AND** o bot confirma que nada foi feito

#### Scenario: Admin envia outro comando real em vez de responder o prompt

- **GIVEN** o bot perguntou se deve criar o contato e está aguardando o
  nome
- **WHEN** o admin envia, em vez de um nome, um comando reconhecível
  (ex. "apaga o contato do Pedro")
- **THEN** o prompt pendente é abandonado (sem criar contato algum com o
  texto do comando como nome)
- **AND** o comando enviado é processado normalmente, como se não houvesse
  nenhum prompt pendente

### Requirement: Admin renomeia um contato

Um admin DEVE poder alterar o nome (`push_name`) de um contato existente
através de um comando em linguagem natural, resolvendo o alvo por nome
(com desambiguação quando houver mais de um) ou por telefone.

#### Scenario: Renomear por nome, match único

- **GIVEN** um único contato correspondendo ao nome informado
- **WHEN** o admin envia "renomeia o Pedro para Pedro Silva"
- **THEN** o `push_name` do contato vira "Pedro Silva"
- **AND** o admin recebe confirmação

#### Scenario: Renomear por telefone

- **WHEN** o admin envia "muda o nome do 5511999999999 para Maria Souza"
- **THEN** o `push_name` do contato com esse telefone vira "Maria Souza"

#### Scenario: Nome ambíguo desambigua antes de renomear

- **GIVEN** mais de um contato correspondendo ao nome informado
- **WHEN** o admin envia o comando de renomear
- **THEN** o bot pergunta qual contato, no mesmo formato de desambiguação
  dos demais comandos
- **AND**, ao escolher, o contato certo é renomeado para o novo nome
  originalmente pedido

#### Scenario: Comando sem "para novo nome"

- **WHEN** o admin envia "renomeia o Pedro" (sem indicar o novo nome)
- **THEN** o bot responde explicando o formato esperado
- **AND** nenhum contato é alterado

### Requirement: Excluir contato exige confirmação

Um admin DEVE poder excluir permanentemente um contato (e, por cascata de
schema, todo o seu histórico de mensagens e mídia) através de um comando
em linguagem natural — mas a exclusão NÃO DEVE acontecer sem uma
confirmação explícita numa segunda mensagem, dado que é irreversível.

#### Scenario: Pedido de exclusão pede confirmação, não apaga ainda

- **GIVEN** um contato existente resolvido por nome ou telefone
- **WHEN** o admin envia "apaga o contato do 5511999999999"
- **THEN** o bot pergunta se o admin tem certeza, avisando que o
  histórico será removido e a ação não pode ser desfeita
- **AND** o contato continua existindo no banco

#### Scenario: Confirmação apaga o contato

- **GIVEN** o bot pediu confirmação de exclusão para um contato
- **WHEN** o admin responde "sim"
- **THEN** o contato é removido do banco
- **AND** uma busca subsequente por esse telefone não encontra mais o
  contato nem seu histórico de mensagens

#### Scenario: Resposta diferente de "sim" cancela

- **GIVEN** o bot pediu confirmação de exclusão para um contato
- **WHEN** o admin responde qualquer coisa que não seja uma confirmação
  ("sim"/"s"/"confirmar"/"confirmo"/"yes")
- **THEN** o contato NÃO é apagado
- **AND** o bot confirma que a exclusão foi cancelada

#### Scenario: Admin envia outro comando real em vez de responder o prompt

- **GIVEN** o bot pediu confirmação de exclusão para um contato e está
  aguardando "sim"/"não"
- **WHEN** o admin envia, em vez de uma confirmação, um comando
  reconhecível não relacionado (ex. "renomeia Maria para Mari")
- **THEN** a exclusão pendente é abandonada (o contato original NÃO é
  apagado)
- **AND** o comando enviado é processado normalmente, como se não houvesse
  nenhuma confirmação pendente

#### Scenario: Nome ambíguo desambigua antes de pedir confirmação

- **GIVEN** mais de um contato correspondendo ao nome informado no comando
  de exclusão
- **WHEN** o admin escolhe qual contato entre os candidatos
- **THEN** só depois disso o bot pede confirmação de exclusão para o
  contato escolhido

