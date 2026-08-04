# Delta: instagram

## ADDED Requirements

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
