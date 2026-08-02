# Serviço de ingestão do webhook do Instagram

## Why

O fluxo de produção atual (`windmill/f/whatbot/handler.py` →
`whatbot.main.main(payload)`) é síncrono e chama o modelo antes de responder
ao webhook. A Meta exige handshake `GET` de verificação, validação de
assinatura sobre o corpo bruto, e resposta em menos de 20 segundos — se o
processamento (que inclui a chamada ao LLM) acontece antes da confirmação, um
dia de latência ruim gera reentrega, e reentrega sem idempotência gera
resposta duplicada ao cliente.

Hoje `InboundMessage.to_payload()` já propaga o `message_id` do canal (fruto
de `harden-channel-layer`), mas nada consome esse campo — não há tabela
`webhook_eventos`, não há checagem de duplicata em lugar nenhum do caminho de
processamento.

## What Changes

- Serviço de ingestão HTTP dedicado (`whatbot/ingress.py`), separado do ciclo
  síncrono do Windmill, com handshake de verificação e validação de
  assinatura em tempo constante sobre o corpo bruto.
- Confirmação imediata da entrega; processamento (incluindo chamada ao
  modelo) acontece fora do ciclo de resposta ao webhook.
- Descarte de evento duplicado pelo identificador de mensagem
  (`webhook_eventos`, criada em `identity-multichannel`).
- Serviço registrado no `docker-compose.yml`, dependências novas em
  `requirements.txt`.
- Scripts operacionais espelhando os já existentes para WhatsApp: OAuth,
  renovação de token, assinatura de webhook, health check, simulação de
  webhook.
- Job agendado de renovação automática de token, com alerta ao admin quando a
  credencial está perto de expirar.

## Impact

- Specs afetadas: `instagram`
- Código novo: `whatbot/ingress.py`, `scripts/ig_oauth.py`,
  `scripts/ig_refresh_token.py`, `scripts/ig_subscribe_webhook.py`,
  `scripts/ig_health_check.py`, `scripts/ig_simulate_webhook.py`,
  `windmill/f/whatbot/refresh_ig_token.py`
- Código/infra alterados: `docker-compose.yml`, `requirements.txt`
- Testes novos: `tests/test_webhook_signature.py`; testes do endpoint FastAPI
  com `TestClient`, sem rede real; teste de idempotência ao nível de
  `main()` (segunda entrega do mesmo `message_id` não gera segunda resposta)
  adicionado a `tests/test_main_e2e.py`
- Bloqueado por: `identity-multichannel` (tabelas `webhook_eventos` e
  `canal_credenciais`), `instagram-channel-client` (usa o parser e o cliente
  para montar o payload processado)
- Não depende de `instagram-webhook-exposure` para os testes automatizados
  (que rodam sem rede) — só para a homologação real com a Meta
