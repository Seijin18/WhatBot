# Smoke test real do Instagram Direct

## Why

`instagram-go-live` (homologação formal de 14 casos, canário de 3 dias),
`instagram-webhook-exposure` (domínio/certificado permanentes) e
`instagram-operability` (runbook completo) foram desenhados para uma
operação já madura. Isso é o alvo certo — mas exige investimento
significativo antes de sabermos se o esqueleto (identidade, janela,
ingestão, idempotência) realmente funciona contra a API real da Meta, que
tem particularidades que nenhum teste com fake reproduz por completo.

Decisão: inverter a ordem. Este change valida o mínimo necessário — uma
mensagem real do Instagram Direct chegando e sendo respondida
corretamente, sem duplicar, sem vazar a janela de mensageria — usando
infraestrutura provisória (túnel HTTPS, não domínio definitivo) e um
canário de uma única pessoa (o próprio operador), não abertura formal. Os
três changes maduros citados acima ficam **adiados**, com nota explícita
nos seus `proposal.md`, retomados só depois que este smoke test provar que
o esqueleto funciona — e o que ele revelar quebrado vira a próxima tarefa
concreta, priorizada pelo impacto observado.

Todo o código que este change exercita já existe e está testado
isoladamente: `identity-multichannel`, `channel-queue-visibility`,
`instagram-channel-client`, `instagram-messaging-window`,
`instagram-ingestion-service` (todos commitados). O que falta é ligar as
pontas em produção e observar o comportamento real pela primeira vez.

## What Changes

- Túnel HTTPS temporário (cloudflared/ngrok ou equivalente) expondo só a
  porta de `whatbot-ingress` (`IG_INGRESS_PORT`) — não a exposição
  permanente de `instagram-webhook-exposure`.
- `.env` preenchido com as credenciais já obtidas pelo usuário no Meta
  Developer (`IG_APP_ID`, `IG_CLIENT_SECRET`, `IG_APP_SECRET`) + variáveis
  geradas para este teste (`IG_WEBHOOK_VERIFY_TOKEN`,
  `IG_OAUTH_REDIRECT_URI` apontando para o túnel).
- Token de longa duração obtido via `scripts/ig_oauth.py` e persistido em
  `canal_credenciais`.
- Webhook assinado via `scripts/ig_subscribe_webhook.py` contra a URL do
  túnel.
- `InstagramClient` registrado em `whatbot/main.py::_init_infra()`, usando
  obrigatoriamente `instagram_last_inbound_lookup(_db)` como
  `last_inbound_lookup` — não o método do banco direto, que deixaria o
  cliente fail-closed 100% do tempo (risco já documentado em
  `instagram-messaging-window`).
- `TEST_IGSIDS` com um único IGSID: o do próprio operador.
- Checklist mínimo de smoke test, documentado com evidência (não os 14
  casos formais de `instagram-go-live`).

## Impact

- Specs afetadas: nenhuma nova — este change só configura/liga o que já
  está especificado e implementado em `identity-multichannel`,
  `instagram-channel-client`, `instagram-messaging-window` e
  `instagram-ingestion-service`.
- Código alterado: `whatbot/main.py` (registro do `InstagramClient`)
- Sem teste automatizado novo — usa a suíte já verde como pré-condição. A
  validação real é o checklist manual contra a conta real, documentado no
  `tasks.md`.
- Infraestrutura: túnel HTTPS provisório (não versionado, efêmero),
  `.env` local preenchido pelo usuário.
- Bloqueado por: `identity-multichannel`, `channel-queue-visibility`,
  `instagram-channel-client`, `instagram-messaging-window`,
  `instagram-ingestion-service` (todos prontos).
- **Substitui, para esta fase**, a execução de `instagram-webhook-exposure`,
  `instagram-go-live` e `instagram-operability` — ver nota de adiamento nos
  `proposal.md` de cada um.
