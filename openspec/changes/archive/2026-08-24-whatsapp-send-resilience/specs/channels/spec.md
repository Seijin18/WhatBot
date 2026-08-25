# Delta: channels

## ADDED Requirements

### Requirement: Roteador tenta de novo falha retryable, uma vez só o suficiente

`ChannelRouter.send_text` DEVE, ao receber `ChannelError(retryable=True)` de
um cliente de canal, tentar o envio de novo com um backoff curto (segundos,
não minutos) antes de desistir e propagar o erro. Uma
`ChannelError(retryable=False)` DEVE propagar imediatamente, sem tentativa
adicional. Isso vale para qualquer canal (`Evolution`, `Instagram`,
`WhatsAppCloudClient`) — o retry mora no roteador, não em cada cliente.

#### Scenario: Falha transitória de rede se recupera sozinha

- **WHEN** `send_text` recebe `ChannelError(retryable=True)` na primeira
  tentativa e a tentativa seguinte tem sucesso
- **THEN** o chamador recebe o resultado de sucesso, sem saber que houve
  uma falha intermediária

#### Scenario: Erro não-retryable não tenta de novo

- **WHEN** `send_text` recebe `ChannelError(retryable=False)`
- **THEN** o erro propaga imediatamente, sem nenhuma tentativa adicional

#### Scenario: Falha persiste além do número de tentativas

- **WHEN** todas as tentativas (incluindo a inicial) falham com
  `ChannelError(retryable=True)`
- **THEN** o último erro propaga ao chamador, como se não houvesse retry

### Requirement: Alerta de sequência de falhas cobre qualquer canal

O rastreamento de sequência de falhas de envio (`canal_envio_falhas`,
`record_send_result`) DEVE ser aplicado a qualquer canal com cliente
registrado, não só ao Instagram — a tabela e o limiar configurável já eram
genéricos por `canal`; só a chamada em `whatbot/main.py` estava restrita.

#### Scenario: Sequência de falhas do WhatsApp dispara alerta

- **WHEN** o envio ao cliente falha `IG_ALERT_FAIL_STREAK` vezes seguidas no
  canal WhatsApp
- **THEN** um alerta é enviado ao admin, do mesmo jeito que já acontece hoje
  para o Instagram
