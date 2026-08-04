# Delta: campaigns

## ADDED Requirements

### Requirement: Importação valida linha a linha sem falhar o lote inteiro

A importação de um CSV de disparo DEVE aceitar as colunas `telefone` e
`mensagem` (obrigatórias) e `tipo_cliente` (opcional). Uma linha inválida
(telefone não normalizável ou mensagem vazia) DEVE ser reportada
individualmente, sem impedir que as demais linhas válidas do mesmo arquivo
sejam enfileiradas.

#### Scenario: CSV totalmente válido

- **WHEN** um CSV com todas as linhas válidas é importado
- **THEN** toda linha vira um registro em `disparo_mensagens` com
  `status = "pendente"`

#### Scenario: Uma linha com telefone inválido não derruba o lote

- **GIVEN** um CSV com 10 linhas, uma delas com telefone que não
  normaliza para um número válido
- **WHEN** o CSV é importado
- **THEN** as 9 linhas válidas são enfileiradas como `pendente`
- **AND** a linha inválida é reportada ao admin com o número da linha e o
  motivo
- **AND** nenhum registro é criado para a linha inválida

#### Scenario: Coluna `tipo_cliente` opcional atualiza contato existente

- **GIVEN** uma linha do CSV com `tipo_cliente = "b2b"` para um telefone
  que já corresponde a um contato existente
- **WHEN** o CSV é importado
- **THEN** o `tipo_cliente` desse contato é atualizado para `"b2b"`
- **AND** a ausência dessa coluna, ou um contato que ainda não existe, não
  impede a linha de ser enfileirada normalmente

### Requirement: Envio em lote respeita limite configurável de taxa

O envio das mensagens enfileiradas DEVE acontecer em lotes de tamanho
limitado, com uma pausa mínima configurável entre cada envio dentro do
lote, para não gerar uma rajada de mensagens.

#### Scenario: Execução do worker respeita o tamanho de lote

- **GIVEN** mais linhas `pendente` na fila do que `CAMPAIGN_BATCH_SIZE`
- **WHEN** o worker roda uma vez
- **THEN** só `CAMPAIGN_BATCH_SIZE` linhas são processadas nessa execução
- **AND** as demais continuam `pendente` para a próxima execução

#### Scenario: Pausa entre envios do mesmo lote

- **WHEN** o worker envia mais de uma mensagem na mesma execução
- **THEN** espera pelo menos `CAMPAIGN_SEND_INTERVAL_SECONDS` entre um
  envio e o próximo

### Requirement: Falha de envio tem retry limitado e observável

Uma falha de envio classificada como retentável DEVE ser tentada de novo
até um limite configurável de tentativas antes de ser marcada como falha
definitiva. Uma falha não retentável DEVE ser marcada como falha
definitiva imediatamente, sem consumir tentativas.

#### Scenario: Falha retentável dentro do limite volta para a fila

- **GIVEN** uma linha cujo envio falha com um erro retentável (ex.: erro
  de transporte) e `tentativas` ainda abaixo de `CAMPAIGN_MAX_RETRIES`
- **WHEN** o worker processa essa linha
- **THEN** `tentativas` é incrementado
- **AND** `status` permanece `pendente` para nova tentativa numa execução
  futura

#### Scenario: Falha retentável esgota tentativas

- **GIVEN** uma linha que já atingiu `CAMPAIGN_MAX_RETRIES` tentativas
- **WHEN** o envio falha de novo com erro retentável
- **THEN** `status` vira `falha`, com a mensagem de erro registrada

#### Scenario: Falha não retentável não consome tentativas

- **GIVEN** uma linha cujo envio falha com um erro não retentável
- **WHEN** o worker processa essa linha
- **THEN** `status` vira `falha` imediatamente, com o erro registrado
- **AND** nenhuma tentativa adicional é feita

### Requirement: Contato com bot pausado não recebe disparo em massa

Uma linha da fila cujo contato correspondente está com `ia_ativa = FALSE`
no momento do envio NÃO DEVE ser enviada — deve ser marcada como pulada.

#### Scenario: Contato pausado é pulado, não enviado

- **GIVEN** uma linha `pendente` cujo contato tem `ia_ativa = FALSE`
  (handover em andamento ou pausa manual de admin)
- **WHEN** o worker chega nessa linha
- **THEN** `status` vira `pulado`
- **AND** nenhuma mensagem é enviada para esse contato
