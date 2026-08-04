# Delta: instagram

## ADDED Requirements

### Requirement: Idempotência de entrega de webhook

Um evento de webhook já processado DEVE ser descartado se reentregue, usando
o identificador de mensagem do canal (`message_id`, já propagado por
`InboundMessage.to_payload()`).

A Meta reentrega eventos quando não recebe confirmação a tempo; sem isso o
cliente receberia resposta duplicada.

#### Scenario: Reentrega do mesmo evento

- **WHEN** o mesmo evento chega duas vezes
- **THEN** só a primeira gera resposta
- **AND** a segunda é descartada sem erro

### Requirement: Autenticidade e velocidade da ingestão

O endpoint de webhook DEVE responder ao handshake de verificação apenas com
o token configurado, DEVE recusar requisição cuja assinatura sobre o corpo
bruto não confira (comparação em tempo constante), e DEVE confirmar o
recebimento antes de processar a mensagem.

O processamento — que inclui chamada ao modelo — NÃO DEVE acontecer dentro
do ciclo de resposta ao webhook.

#### Scenario: Assinatura inválida

- **WHEN** chega uma requisição com assinatura que não confere
- **THEN** é recusada
- **AND** nada é processado

#### Scenario: Confirmação rápida

- **WHEN** chega um evento válido
- **THEN** a confirmação é devolvida imediatamente
- **AND** o processamento da mensagem acontece fora do ciclo de resposta

### Requirement: Renovação automática de credencial

A credencial de acesso do Instagram DEVE ser renovada automaticamente antes
de expirar, e a proximidade da expiração DEVE gerar alerta ao admin.

Expiração silenciosa de token é a principal causa de queda dessa integração
em produção.

#### Scenario: Credencial perto de expirar

- **WHEN** a credencial está a menos de uma semana de expirar
- **THEN** o admin é alertado pelo canal de admin

#### Scenario: Renovação automática bem-sucedida

- **WHEN** o job agendado de renovação roda antes da expiração
- **THEN** a credencial é renovada sem intervenção manual
- **AND** nenhum alerta é gerado se a renovação teve sucesso

### Requirement: Alertas de saúde da integração

Além da renovação de credencial, o admin DEVE ser alertado quando: uma
sequência de falhas de envio consecutivas atinge `IG_ALERT_FAIL_STREAK`
(default: 5), ou nenhum evento de webhook é recebido por
`IG_ALERT_SILENCE_MINUTES` (default: 120) minutos — indicando possível queda
da assinatura ou do túnel de exposição. Os dois limiares DEVEM ser
configuráveis por variável de ambiente, com o default documentado aqui.

#### Scenario: Sequência de falhas de envio atinge o limiar

- **WHEN** o envio pelo canal Instagram falha `IG_ALERT_FAIL_STREAK` vezes
  consecutivas
- **THEN** o admin é alertado pelo canal de admin, identificando o canal com
  falha
- **AND** um envio bem-sucedido no meio da sequência zera a contagem

#### Scenario: Ausência prolongada de eventos

- **WHEN** nenhum evento de webhook do Instagram é recebido por mais de
  `IG_ALERT_SILENCE_MINUTES` minutos
- **THEN** o admin é alertado, para investigar queda de assinatura ou de
  exposição HTTPS

#### Scenario: Abaixo do limiar não gera alerta

- **WHEN** falhas de envio ocorrem mas não atingem `IG_ALERT_FAIL_STREAK`
  consecutivas, ou o silêncio de webhook está abaixo de
  `IG_ALERT_SILENCE_MINUTES`
- **THEN** nenhum alerta é gerado
