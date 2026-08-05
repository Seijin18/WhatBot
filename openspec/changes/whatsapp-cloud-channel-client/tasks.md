# Tasks — migração do WhatsApp para a Cloud API

## 1. Cliente

- [x] 1.1 `whatbot/channels/whatsapp_cloud.py`: implementa `ChannelClient`
      sobre `graph.facebook.com/<version>/<phone_number_id>/messages`,
      `canal = WHATSAPP` (mesmo valor do cliente Evolution — ver `design.md`)
      (→ Requirement "Cliente Cloud API implementa o contrato de canal")
- [x] 1.2 Mapeia erros da Cloud API (token expirado, número não opt-in,
      limite de mensageria, rate limit) para causas tipadas de
      `ChannelError`, `retryable` correto por causa. Códigos verificados
      contra a doc atual da Meta (não copiados do Instagram): `190`/`0`/`200`
      → `invalid_token`; `4`/`80007`/`130429`/`131056` → `rate_limited`;
      `131047`/`131049` → `outside_window`; `131026`/`131050` →
      `not_opted_in` (`error_subcode` não usado — deprecado nesta API desde
      v16.0, diferente do Instagram)
      (→ Requirement "Erros da Cloud API são identificados por tipo")
- [x] 1.3 `split_text`/`MAX_TEXT_LENGTH=4096` (confirmado contra a doc atual
      da Cloud API — 4x o limite do Instagram) — mantido por simetria de
      contrato entre canais, não porque se espera disparar na prática
      (`test_typical_reply_stays_a_single_block`)

## 2. Webhook / parser

- [x] 2.1 `whatbot/whatsapp_cloud_webhook.py`: parser de mensagem comum da
      Cloud API, produzindo `InboundMessage`
      (→ Requirement "Parser reconhece formato de mensagem da Cloud API")
- [x] 2.2 Casos de borda: mensagem só com mídia, status de entrega
      (`statuses` no payload, não é mensagem nova), múltiplos eventos por
      POST, múltiplos `entry`/`changes` num POST
      (→ idem, cenários correspondentes)
- [x] 2.3 `whatbot/ingress.py`: nova rota `GET/POST /webhook/whatsapp`
      reaproveitando `verify_handshake`/`verify_signature`/`_process_event`
      (já agnósticos de produto) sem duplicar o handshake `hub.challenge` —
      decisão tomada em `design.md`: duplicar o par de rotas literalmente
      (2 produtos hoje), não construir uma tabela de rotas genérica (YAGNI)
      (→ Requirement "Ingress roteia por produto Meta")

## 3. Configuração e credenciais

- [x] 3.1 `WHATSAPP_PROVIDER` (`evolution` default | `cloud`) +
      `resolve_whatsapp_provider()` em `whatbot/config.py`, lido por
      `whatbot/main.py::_init_infra()` na hora de registrar o client em
      `ChannelRouter`. Achado durante a implementação: a atribuição de
      `_router` ao global precisou ficar depois do registro bem-sucedido
      (não antes), senão uma falha no branch `cloud` (`RuntimeError`)
      deixaria `_router` parcialmente inicializado em vez de `None`,
      quebrando a possibilidade de retry — corrigido, coberto por
      `test_main_infra.py::test_cloud_provider_without_credential_fails_loud`
- [x] 3.2 `canal_credenciais` (`canal='whatsapp'`): grava token de longa
      duração + `account_id=phone_number_id`, reaproveitando a tabela já
      existente — nenhuma migração de schema (confirmado, `db.py` já
      genérico por `canal`)
- [x] 3.3 Documentado em `DEPLOYMENT.md` (seção "Alternativa: WhatsApp Cloud
      API") e `.env.example` — pré-requisitos no Meta Business Manager, env
      vars, `INSERT`/`UPDATE` em `canal_credenciais` (sem fluxo OAuth, ao
      contrário do Instagram — System User token é direto)

## 4. Testes

- [x] 4.1 `tests/test_whatsapp_cloud_client.py`: envio normal, cada causa de
      `ChannelError`, sem rede (`requests` mockado) — mesmo padrão de
      `tests/test_evolution_client.py` / `tests/test_instagram_client.py`
- [x] 4.2 `tests/test_whatsapp_cloud_webhook.py`: parser para o formato
      comum e cada caso de borda, sem rede
- [x] 4.3 Estendido `tests/test_channel_contracts.py`
      (`TestWhatsAppCloudClientProtocolAlignment`): cliente Cloud API
      satisfaz o protocolo `ChannelClient`
- [x] 4.4 Desvio deliberado do plano original: em vez de estender
      `tests/test_main_e2e.py` (que faz
      `patch.object(main_mod, "_init_infra", lambda: None)`, contornando
      completamente o branch de seleção de provedor), criado
      `tests/test_main_infra.py`, que chama `_init_infra()` de verdade com
      `_db`/`_llm` já pré-setados (sem Postgres/LLM real) — é o único jeito
      de exercitar a lógica de registro em si. `test_main_e2e.py` continua
      sem alteração, provando que o domínio segue agnóstico de canal.
- [x] 4.5 Suíte completa verde — 486 testes, 0 falhas
      (`.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`)

## 5. Adiado (fora deste change, ver `design.md` "Fora de escopo")

- Homologação/App Review da Meta, verificação do número de negócio — feito
  pelo usuário no Meta Business Manager, fora do código.
- Troca do default de `WHATSAPP_PROVIDER` para `cloud` — change futuro de
  "go-live", só depois de validado contra tráfego real.
- Remoção do Evolution API / Baileys do `docker-compose.yml`.
