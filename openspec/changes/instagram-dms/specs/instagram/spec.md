# Delta: instagram

## ADDED Requirements

### Requirement: Identidade do contato por canal

Um contato DEVE ser identificado pelo par `(canal, external_id)`, onde
`external_id` é o telefone no WhatsApp e o IGSID no Instagram.

A migração DEVE ser aditiva e idempotente: todo contato existente termina com
`canal='whatsapp'` e `external_id` igual ao telefone atual, sem perda de linha e
sem perda de histórico.

Consultas sem canal informado DEVEM assumir `whatsapp`, por compatibilidade.

#### Scenario: Migração de base existente

- **WHEN** a migração roda sobre uma base no formato antigo
- **THEN** todo contato fica com `canal='whatsapp'` e `external_id` igual ao
  telefone anterior
- **AND** nenhuma linha é perdida
- **AND** rodar a migração de novo não altera mais nada

#### Scenario: Mesma identidade externa em canais diferentes

- **WHEN** dois contatos têm o mesmo `external_id` em canais diferentes
- **THEN** são contatos distintos, com históricos separados

### Requirement: Normalização de identidade específica por canal

A normalização de telefone — remoção de não-dígitos e do sufixo de JID — DEVE ser
aplicada apenas a identidades de WhatsApp.

A extração de telefone a partir de texto livre NÃO DEVE casar com um IGSID.

#### Scenario: IGSID não é tratado como telefone

- **WHEN** uma identidade do Instagram atravessa a resolução de contatos
- **THEN** ela não é normalizada como telefone
- **AND** não resolve para um contato de WhatsApp

### Requirement: Janela de mensageria de 24 horas

Antes de qualquer envio pelo Instagram, a janela de mensageria DEVE ser
verificada contra o último recebimento daquele contato.

- Dentro de 24 h: envio normal.
- Fora de 24 h, em atendimento humano: envio sob permissão de atendimento
  humano, válida por até 7 dias.
- Fora de 24 h, mensagem automática do bot: o envio NÃO DEVE acontecer; a
  tentativa é registrada e devolve falha identificada.

#### Scenario: Mensagem automática fora da janela

- **WHEN** o bot tentaria enviar automaticamente a um contato silencioso há mais
  de 24 h
- **THEN** nada é enviado
- **AND** o resultado identifica a janela como motivo da recusa

#### Scenario: Atendimento humano fora da janela

- **WHEN** a secretaria responde a um contato silencioso há mais de 24 h e menos
  de 7 dias
- **THEN** a mensagem é entregue sob a permissão de atendimento humano

### Requirement: Idempotência de entrega de webhook

Um evento de webhook já processado DEVE ser descartado se reentregue, usando o
identificador de mensagem do canal.

A Meta reentrega eventos quando não recebe confirmação a tempo; sem isso o
cliente receberia resposta duplicada.

#### Scenario: Reentrega do mesmo evento

- **WHEN** o mesmo evento chega duas vezes
- **THEN** só a primeira gera resposta
- **AND** a segunda é descartada sem erro

### Requirement: Autenticidade e velocidade da ingestão

O endpoint de webhook DEVE responder ao handshake de verificação apenas com o
token configurado, DEVE recusar requisição cuja assinatura sobre o corpo bruto
não confira, e DEVE confirmar o recebimento antes de processar a mensagem.

O processamento — que inclui chamada ao modelo — NÃO DEVE acontecer dentro do
ciclo de resposta ao webhook.

#### Scenario: Assinatura inválida

- **WHEN** chega uma requisição com assinatura que não confere
- **THEN** é recusada
- **AND** nada é processado

#### Scenario: Confirmação rápida

- **WHEN** chega um evento válido
- **THEN** a confirmação é devolvida imediatamente
- **AND** o processamento da mensagem acontece fora do ciclo de resposta

### Requirement: Renovação automática de credencial

A credencial de acesso do canal DEVE ser renovada automaticamente antes de
expirar, e a proximidade da expiração DEVE gerar alerta ao admin.

Expiração silenciosa de token é a principal causa de queda dessa integração em
produção.

#### Scenario: Credencial perto de expirar

- **WHEN** a credencial está a menos de uma semana de expirar
- **THEN** o admin é alertado pelo canal de admin

### Requirement: Fila identifica o canal de origem

Notificações e listagens da fila DEVEM identificar o canal e o identificador
legível do contato, para que a secretaria saiba por onde responder.

Quando o canal impõe prazo de resposta, a notificação DEVE informá-lo.

#### Scenario: Novo item de outro canal na fila

- **WHEN** um contato de canal não-WhatsApp entra na fila
- **THEN** a notificação ao admin identifica o canal e o contato
- **AND** informa o prazo de resposta do canal

### Requirement: Lançamento controlado por lista de teste

O canal novo DEVE poder operar restrito a uma lista de contas de teste, como já
acontece no WhatsApp, para canário antes da abertura geral.

Fora da lista, durante o canário, a mensagem NÃO DEVE receber resposta
automática.

#### Scenario: Contato fora da lista durante o canário

- **WHEN** um contato fora da lista de teste manda mensagem com o canário ativo
- **THEN** nenhuma resposta automática é enviada
