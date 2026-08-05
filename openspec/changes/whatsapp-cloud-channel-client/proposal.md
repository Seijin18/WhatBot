# Migração do WhatsApp para a API oficial (Cloud API)

## Why

O canal `whatsapp` hoje é implementado só sobre a Evolution API (Baileys —
`whatbot/channels/whatsapp_evolution.py`), uma integração não-oficial que
simula um cliente WhatsApp comum. Baileys está sujeito a bugs de protocolo
fora do nosso controle: nesta sessão de operação, envios ficaram presos em
`status: 0` / `messageStubParameters: ["463"]` (`NackCallerReachoutTimelocked`
— rate-limit de privacidade do próprio WhatsApp para contato "frio"/sessão
recém-pareada), documentado como bug aberto em
[evolution-foundation/evolution-api#2653](https://github.com/evolution-foundation/evolution-api/issues/2653)
e [WhiskeySockets/Baileys#2698](https://github.com/WhiskeySockets/Baileys/issues/2698),
sem fix confirmado até a data. O sintoma prático: a API reporta envio como
bem-sucedido, mas a mensagem nunca chega no destinatário — silencioso e
indetectável sem inspecionar logs internos do Baileys.

A API oficial da Meta (WhatsApp Cloud API, `graph.facebook.com`) não tem essa
classe de bug — é o mesmo protocolo usado pela Meta para clientes
Business API pagantes, sem simulação de cliente humano. O projeto já resolveu
exatamente esse tipo de integração para o Instagram
(`openspec/changes/archive/2026-08-04-instagram-channel-client/`), incluindo
webhook `hub.challenge`, parser Meta, e cliente de canal — este change segue
o mesmo padrão para WhatsApp.

## What Changes

- `whatbot/channels/whatsapp_cloud.py`: novo `ChannelClient` sobre
  `graph.facebook.com/v.../<phone_number_id>/messages`, registrado sob o
  **mesmo** nome de canal `"whatsapp"` (não um canal novo) — ver `design.md`
  para a decisão de substituição vs. coexistência.
- `whatbot/whatsapp_cloud_webhook.py`: parser de webhook da Cloud API,
  produzindo `InboundMessage` (mesmo contrato usado por
  `whatbot/instagram_webhook.py` e pelo parser Evolution existente).
- Reaproveita `whatbot/ingress.py` (handshake `hub.challenge`,
  `X-Hub-Signature-256`) já construído para o Instagram — mesmo protocolo
  Meta, só muda o parser de payload e a rota.
- `canal_credenciais`: novo registro `canal='whatsapp'` guardando o token de
  longa duração (System User token) e `account_id` = `phone_number_id`,
  mesmo padrão já usado pelo Instagram.
- Flag de seleção de provedor (`WHATSAPP_PROVIDER=cloud|evolution`, default
  a decidir em `design.md`) para permitir rollback rápido para Evolution
  sem reverter código, enquanto a Cloud API não está validada em produção.
- **Não migra** `whatbot/channels/whatsapp_evolution.py` nem o
  `docker-compose.yml` do Evolution API — ambos continuam existindo até a
  Cloud API estar validada (ver tasks de corte/remoção no final de
  `tasks.md`, deliberadamente adiadas).

## Impact

- Specs afetadas: `whatsapp-cloud` (nova capability, espelhando `instagram` —
  inclui o requirement de seleção de provedor dentro do canal `whatsapp`)
- Código novo: `whatbot/channels/whatsapp_cloud.py`,
  `whatbot/whatsapp_cloud_webhook.py`
- Código estendido: `whatbot/ingress.py` (nova rota/parser), `whatbot/db.py`
  (nenhuma migração de schema — `canal_credenciais` e `webhook_eventos` já
  são genéricos por `canal`), `whatbot/channels/router.py` (nenhuma mudança
  de contrato — só troca de qual client é registrado sob `"whatsapp"`)
- Testes novos: `tests/test_whatsapp_cloud_client.py`,
  `tests/test_whatsapp_cloud_webhook.py`, sem rede, seguindo o padrão de
  `tests/test_instagram_client.py` / `tests/test_instagram_webhook.py`
- **Identidade não muda**: `external_id` do WhatsApp continua sendo o
  telefone E.164, então contatos existentes (`contatos.canal='whatsapp'`)
  continuam válidos sem migração — diferente do Instagram, que introduziu
  `identity-multichannel` porque criava uma identidade nova. Este change
  não depende de `identity-multichannel`.
- Não bloqueia nem é bloqueado por nenhum change ativo de Instagram —
  canais independentes, mesmo padrão de implementação.
