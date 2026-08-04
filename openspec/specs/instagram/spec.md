# instagram Specification

## Purpose
TBD - created by archiving change instagram-channel-client. Update Purpose after archive.
## Requirements
### Requirement: Cliente Instagram implementa o contrato de canal

`whatbot/channels/instagram.py` DEVE implementar o protocolo `ChannelClient`
já definido em `openspec/specs/channels/spec.md` ("Contrato único de canal"),
expondo `canal = "instagram"` e `send_text` com a mesma assinatura keyword-only
usada pelo cliente WhatsApp.

#### Scenario: Cliente aceita a chamada por keyword do roteador

- **WHEN** o `ChannelRouter` despacha para o cliente Instagram
- **THEN** a chamada é aceita com os mesmos parâmetros nomeados usados para
  qualquer outro canal

### Requirement: Erros de canal são identificados por tipo

O cliente Instagram DEVE sinalizar falha com `ChannelError`, identificando
qual das seguintes causas ocorreu: janela de mensageria expirada
(`cause="window_expired"`), permissão de atendimento humano ausente, ou rate
limit (com informação de backoff quando disponível).

Este requisito cobre o **mecanismo** de sinalização — quando a API do
Instagram responde recusando o envio, o cliente traduz a resposta em
`ChannelError` com a causa correta. A **política** de quando um envio está
dentro ou fora da janela (consulta a `last_inbound_at`, antes mesmo de
chamar a API) é responsabilidade de `instagram-messaging-window`, que
adiciona essa checagem prévia dentro deste mesmo cliente — ver
`openspec/changes/instagram-messaging-window/design.md`.

#### Scenario: API recusa envio por janela expirada

- **WHEN** a API do Instagram responde recusando o envio por motivo de
  janela de mensageria
- **THEN** `ChannelError(cause="window_expired")` é levantada

#### Scenario: Rate limit da API

- **WHEN** a API do Instagram responde com limite de taxa excedido
- **THEN** `ChannelError` é levantada identificando rate limit, com o tempo
  de backoff quando informado pela API

### Requirement: Mensagem longa é dividida preservando ordem

Uma mensagem de saída que exceda o limite de tamanho do Instagram Direct DEVE
ser dividida em blocos menores, entregues na ordem original.

#### Scenario: Resposta longa do bot

- **WHEN** o bot gera uma resposta maior que o limite do canal
- **THEN** a mensagem é dividida em blocos
- **AND** os blocos são entregues na ordem em que o texto original os continha

### Requirement: Parser reconhece formatos e casos de borda do Instagram

`whatbot/instagram_webhook.py` DEVE reconhecer e tratar explicitamente: eco
da própria secretaria respondendo pelo app do Instagram, menção e resposta a
story, mensagem contendo só mídia sem texto, notificação de mensagem
apagada, e múltiplos eventos dentro de um único POST do webhook.

Em nenhum desses casos o parser DEVE lançar exceção não tratada; casos que
não geram resposta automática DEVEM ser distinguíveis de erro de parsing.

#### Scenario: Eco da secretaria pelo app do Instagram

- **WHEN** chega um evento de mensagem enviada pela própria conta comercial
  (não pelo bot)
- **THEN** é reconhecido como eco de atendimento humano, análogo ao `fromMe`
  do WhatsApp
- **AND** não gera resposta automática do bot

#### Scenario: Mensagem só com mídia

- **WHEN** chega uma mensagem sem campo de texto, só com anexo
- **THEN** o parser processa sem erro, sem assumir que o texto existe

#### Scenario: Mensagem apagada

- **WHEN** chega uma notificação de mensagem apagada
- **THEN** é distinguida de uma mensagem nova
- **AND** não gera resposta a um texto vazio

#### Scenario: Múltiplos eventos num POST

- **WHEN** um único POST do webhook contém mais de um evento
- **THEN** todos os eventos são processados
- **AND** nenhum é ignorado silenciosamente

### Requirement: Janela de mensageria de 24 horas

Antes de qualquer envio pelo Instagram, a janela de mensageria DEVE ser
verificada contra o último recebimento daquele contato (`last_inbound_at`).

- Dentro de 24 h: envio normal.
- Fora de 24 h, em atendimento humano: envio sob permissão de atendimento
  humano (`human_agent=True`), válida por até 7 dias.
- Fora de 7 dias, ou fora de 24h sem atendimento humano: o envio NÃO DEVE
  acontecer; a tentativa é registrada e devolve falha identificada.

Reativação automática do bot (encerramento de handover) NÃO DEVE gerar
mensagem proativa — o bot só volta a responder na próxima mensagem do
cliente.

#### Scenario: Mensagem automática dentro da janela

- **WHEN** o bot responde a um contato que escreveu há menos de 24h
- **THEN** a mensagem é enviada normalmente

#### Scenario: Mensagem automática fora da janela

- **WHEN** o bot tentaria enviar automaticamente a um contato silencioso há
  mais de 24h
- **THEN** nada é enviado
- **AND** o resultado identifica a janela como motivo da recusa

#### Scenario: Atendimento humano fora da janela de 24h

- **WHEN** a secretaria responde a um contato silencioso há mais de 24h e
  menos de 7 dias
- **THEN** a mensagem é entregue sob a permissão de atendimento humano

#### Scenario: Fora da janela de 7 dias mesmo com atendimento humano

- **WHEN** a secretaria tenta responder a um contato silencioso há mais de 7
  dias
- **THEN** o envio é recusado, com falha identificada

#### Scenario: Reativação automática não é proativa

- **WHEN** um handover é encerrado e o bot volta a responder automaticamente
- **THEN** nenhuma mensagem é enviada até que o cliente escreva de novo

### Requirement: Notificação de fila informa prazo de resposta

Quando o canal do contato impõe janela de mensageria, a notificação de fila
(rótulo definido em `channel-queue-visibility`) DEVE informar o prazo restante
de resposta.

#### Scenario: Novo item do Instagram informa prazo

- **WHEN** um contato do Instagram entra na fila
- **THEN** a notificação ao admin informa o prazo de resposta (dentro de
  24h, ou até quando a janela de atendimento humano de 7 dias expira)

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

