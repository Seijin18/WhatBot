# identity Specification

## Purpose
TBD - created by archiving change identity-multichannel. Update Purpose after archive.
## Requirements
### Requirement: Identidade do contato por canal

Um contato DEVE ser identificado pelo par `(canal, external_id)`, onde
`external_id` é o telefone no WhatsApp e o identificador nativo do canal em
qualquer outro canal (ex.: o IGSID no Instagram).

A migração DEVE ser aditiva e idempotente, e DEVE cobrir tanto `contatos`
quanto `handover_historico`: todo registro existente termina com
`canal='whatsapp'` e `external_id` igual ao telefone atual, sem perda de
linha e sem perda de histórico. `phone` permanece nas duas tabelas por
compatibilidade — para contatos de outro canal, `phone` é `NULL` — mas deixa
de ser a chave de identidade.

Consultas sem canal informado DEVEM assumir `whatsapp`, por compatibilidade
com código existente.

#### Scenario: Migração de base existente

- **WHEN** a migração roda sobre uma base no formato antigo
- **THEN** todo contato de `contatos` e todo registro de
  `handover_historico` ficam com `canal='whatsapp'` e `external_id` igual ao
  telefone anterior
- **AND** nenhuma linha é perdida
- **AND** rodar a migração de novo não altera mais nada

#### Scenario: Mesma identidade externa em canais diferentes

- **WHEN** dois contatos têm o mesmo `external_id` em canais diferentes
- **THEN** são contatos distintos, com históricos separados
- **AND** o `INSERT` do segundo contato não é rejeitado pela constraint
  única (a chave é o par `(canal, external_id)`, não `external_id` sozinho)

#### Scenario: Contato de canal não-WhatsApp não usa `phone`

- **WHEN** um contato é criado com `canal != "whatsapp"`
- **THEN** `phone` é gravado como `NULL`
- **AND** nenhum consumidor de `.phone` levanta exceção só por o valor ser
  `None` (rótulo legível e formatação usam `external_id`/`handle` nesse caso)

### Requirement: Normalização de identidade específica por canal

A normalização de telefone — remoção de não-dígitos e do sufixo de JID — DEVE
ser aplicada apenas a identidades de WhatsApp (`canal == "whatsapp"` ou canal
não informado).

A extração de telefone a partir de texto livre NÃO DEVE casar com o
identificador externo de outro canal.

#### Scenario: Identificador de outro canal não é tratado como telefone

- **WHEN** uma identidade de um canal diferente de WhatsApp atravessa a
  resolução de contatos
- **THEN** ela não é normalizada como telefone
- **AND** não resolve para um contato de WhatsApp

### Requirement: Rótulo legível de contato

Todo contato DEVE ter um rótulo legível para exibição, resolvido com
precedência: nome cadastrado → arroba/handle do canal → identidade externa
crua.

O rótulo DEVE ser puro (sem efeito colateral, sem I/O), para que qualquer
consumidor — fila, notificação, log — possa chamá-lo livremente. DEVE
funcionar mesmo quando `phone` é `NULL`.

A fila e as notificações à secretaria DEVEM usar o rótulo legível junto com o
nome do canal, em vez do identificador externo cru.

#### Scenario: Contato sem nome usa handle

- **WHEN** um contato não tem nome cadastrado mas tem handle do canal
- **THEN** o rótulo legível é o handle

#### Scenario: Contato sem nome nem handle usa identidade externa

- **WHEN** um contato não tem nome nem handle
- **THEN** o rótulo legível é a identidade externa crua

#### Scenario: Fila mostra canal e identificador legível

- **WHEN** um contato de qualquer canal entra na fila ou gera uma notificação
  ao admin
- **THEN** a notificação identifica o canal e o rótulo legível do contato
- **AND** não exibe a identidade externa crua quando um rótulo melhor está
  disponível

### Requirement: Filtro de teste por canal

`should_respond_to_customer` DEVE decidir por `(canal, external_id)`. Cada
canal tem sua própria variável de lista de teste (`TEST_PHONES` para
WhatsApp, `TEST_IGSIDS` para Instagram, seguindo a mesma convenção de nome
para canais futuros).

Em `TEST_MODE`, um canal sem lista de teste configurada DEVE bloquear por
padrão (fail-closed) — nunca responder por engano a um público não
pretendido só porque a lista daquele canal está vazia ou ausente.

#### Scenario: TEST_MODE com lista própria configurada

- **WHEN** `TEST_MODE` está ativo e um contato de um canal com lista
  configurada envia mensagem
- **THEN** a resposta é enviada se e somente se a identidade externa do
  contato está na lista daquele canal

#### Scenario: TEST_MODE sem lista configurada para o canal

- **WHEN** `TEST_MODE` está ativo e um canal não tem variável de lista de
  teste configurada
- **THEN** nenhum contato daquele canal recebe resposta automática
  (fail-closed)

#### Scenario: Lista de um canal não vaza para outro

- **WHEN** a identidade externa de um contato de um canal coincide,
  textualmente, com uma entrada da lista de teste de outro canal
- **THEN** isso não autoriza nem bloqueia a resposta — a comparação é sempre
  dentro do mesmo canal

### Requirement: Rastreabilidade por canal no log de mensagens

`log_inbound`, `log_outbound` e `log_llm_turn` DEVEM registrar o `canal` de
cada entrada — incluindo qualquer resumo textual que hoje identifica a
entrada só por `phone` —, para que métricas de erro, latência e volume
possam ser segmentadas por canal.

#### Scenario: Entrada de log traz o canal

- **WHEN** uma mensagem de qualquer canal é processada
- **THEN** a entrada correspondente no destino de log configurado (ver
  `whatbot/message_log.py`, caminho configurável e podendo estar desligado)
  inclui o campo `canal`

