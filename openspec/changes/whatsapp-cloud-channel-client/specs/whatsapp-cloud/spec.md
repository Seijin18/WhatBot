# Delta: whatsapp-cloud

## ADDED Requirements

### Requirement: Cliente Cloud API implementa o contrato de canal

`whatbot/channels/whatsapp_cloud.py` DEVE implementar o protocolo
`ChannelClient` já definido em `openspec/specs/channels/spec.md` ("Contrato
único de canal"), expondo `canal = "whatsapp"` (mesmo valor do cliente
Evolution — ver `design.md` deste change) e `send_text` com a mesma
assinatura keyword-only usada pelos demais canais.

#### Scenario: Cliente aceita a chamada por keyword do roteador

- **WHEN** o `ChannelRouter` despacha para o cliente Cloud API
- **THEN** a chamada é aceita com os mesmos parâmetros nomeados usados para
  qualquer outro canal

#### Scenario: Contatos existentes continuam válidos após a troca de provedor

- **WHEN** `WHATSAPP_PROVIDER` muda de `evolution` para `cloud`
- **THEN** nenhum contato, mensagem ou estado de sessão associado a
  `contatos.canal='whatsapp'` precisa de migração — o `external_id`
  (telefone E.164) é o mesmo nos dois provedores

### Requirement: Erros da Cloud API são identificados por tipo

O cliente Cloud API DEVE sinalizar falha de envio com `ChannelError`,
identificando qual das seguintes causas ocorreu: token de acesso expirado ou
inválido, número de destino sem opt-in/fora da janela de 24h de mensageria
padrão, rate limit (com informação de backoff quando a API informar), ou
falha de transporte (timeout/conexão).

Erros crus da biblioteca HTTP e o corpo de erro estruturado da Meta
(`error.code`, `error.error_subcode`) NÃO DEVEM vazar para os módulos de
domínio — traduzidos em `ChannelError` antes de propagar.

#### Scenario: Token expirado

- **WHEN** a Cloud API responde com erro de autenticação (token expirado ou
  inválido)
- **THEN** `ChannelError` é levantada identificando a causa como token
  inválido, `retryable=False`

#### Scenario: Rate limit da API

- **WHEN** a Cloud API responde com limite de taxa excedido
- **THEN** `ChannelError` é levantada identificando rate limit, com o tempo
  de backoff quando informado pela API, `retryable=True`

#### Scenario: Falha de transporte

- **WHEN** a chamada HTTP falha por timeout ou erro de conexão, sem resposta
  da API
- **THEN** `ChannelError` é levantada com `retryable=True`

### Requirement: Parser reconhece formato de mensagem da Cloud API

`whatbot/whatsapp_cloud_webhook.py` DEVE reconhecer e tratar explicitamente:
mensagem de texto comum, mensagem só com mídia (sem `text`), evento de status
de entrega (`statuses`, que NÃO é uma mensagem nova e não deve gerar
resposta), e múltiplos eventos agrupados num único POST do webhook.

#### Scenario: Mensagem de texto comum

- **WHEN** o webhook recebe uma mensagem de texto de um cliente
- **THEN** o parser produz um `InboundMessage` com `canal="whatsapp"` e o
  texto extraído

#### Scenario: Evento de status de entrega não gera resposta

- **WHEN** o webhook recebe um evento `statuses` (confirmação de entrega,
  leitura, etc.), sem campo de mensagem nova
- **THEN** o parser reconhece o evento e não produz `InboundMessage` nenhum

#### Scenario: Mensagem só com mídia

- **WHEN** a mensagem recebida não tem campo de texto (só imagem/áudio/etc.)
- **THEN** o parser não assume a presença de texto e trata o caso
  explicitamente, sem lançar exceção

#### Scenario: Múltiplos eventos num POST

- **WHEN** o corpo do webhook agrupa mais de um evento de mensagem
- **THEN** o parser itera todos os eventos, sem assumir um único evento por
  requisição

### Requirement: Provedor de WhatsApp selecionável por configuração

O canal `"whatsapp"` DEVE ter exatamente um cliente ativo por vez, escolhido
por `WHATSAPP_PROVIDER` (`evolution` ou `cloud`), resolvido na inicialização
de `whatbot/main.py`. O valor default, enquanto a Cloud API não estiver
homologada em produção, DEVE ser `evolution`.

#### Scenario: Provedor não configurado mantém o comportamento atual

- **WHEN** `WHATSAPP_PROVIDER` não está definido no ambiente
- **THEN** o cliente registrado sob `"whatsapp"` continua sendo
  `EvolutionApiClient`, sem mudança de comportamento

#### Scenario: Provedor explicitamente definido como cloud

- **WHEN** `WHATSAPP_PROVIDER=cloud` está definido no ambiente
- **THEN** o cliente registrado sob `"whatsapp"` é `WhatsAppCloudClient`,
  usando as credenciais de `canal_credenciais` (`canal='whatsapp'`)
