# Design — migração do WhatsApp para a Cloud API

## Decisão: mesmo canal `"whatsapp"`, não um canal novo

Alternativas:

1. **Canal novo** (`whatsapp_cloud`), coexistindo com `whatsapp` (Evolution).
   Rejeitada: `external_id` nos dois casos é o mesmo telefone E.164 — criaria
   dois contatos (`contatos.canal='whatsapp'` e `'whatsapp_cloud'`) para a
   mesma pessoa, fragmentando histórico, fila e `session_state` sem nenhum
   ganho. Também duplicaria `ADMIN_CHANNEL` e toda lógica que hoje assume um
   único canal WhatsApp.
2. **Mesmo canal `"whatsapp"`, cliente trocável por configuração**. Escolhida.
   `ChannelRouter.register()` já resolve por `client.canal` — basta que só
   um dos dois clients (`EvolutionApiClient` ou o novo `WhatsAppCloudClient`)
   seja instanciado e registrado em `whatbot/main.py`, escolhido por
   `WHATSAPP_PROVIDER`. Nenhuma mudança em `db.py`, `router.py`, nem nos
   requirements existentes de `channels/spec.md` — o contrato `ChannelClient`
   já é agnóstico de transporte.

Consequência: contatos, histórico e fila continuam válidos ao trocar de
provedor — a migração é uma troca de implementação por trás do mesmo nome de
canal, não uma migração de dados.

## Decisão: reaproveitar `whatbot/ingress.py`, não duplicar o handshake Meta

O handshake `hub.challenge`/`hub.verify_token` e a verificação
`X-Hub-Signature-256` já existem em `whatbot/ingress.py`, construídos para o
Instagram — são o mesmo protocolo Meta, byte a byte, para qualquer produto
Graph API (Instagram, Messenger, WhatsApp Cloud API). A única coisa que muda
por produto é o **parser do corpo do evento** e a env var de verify token.

Consequência prática: `ingress.py` precisa aceitar múltiplos parsers
registrados por rota (hoje assume implicitamente que só existe o
Instagram) — ver tarefa 2 em `tasks.md`. Isso NÃO é uma reescrita do
handshake, só parametrizar qual parser/verify-token vale para qual path.

## Decisão: `WHATSAPP_PROVIDER` com default `evolution` até validação

A Cloud API exige App Review da Meta e um número verificado antes de operar
fora da equipe de desenvolvimento (mesma restrição de cronograma já discutida
em `docs/INSTAGRAM_INTEGRATION_PLAN.md` para o Instagram). Até essa
homologação, o default do `WHATSAPP_PROVIDER` continua `evolution`
(comportamento atual, inalterado), e o operador liga `cloud` explicitamente
assim que tiver os pré-requisitos da Meta prontos — evita quebrar produção no
meio da migração. Trocar o default para `cloud` é tarefa explícita, adiada
para um change de "go-live" (espelhando `instagram-go-live`), não parte
deste change.

## Decisão: erros tipados espelhando o padrão do WhatsApp/Instagram

Mesma decisão já tomada em `instagram-channel-client/design.md`: `ChannelError`
com causa identificável (`retryable=True` para timeout/erro de rede,
`retryable=False` para rejeição da API — token expirado, número não
verificado, política violada), sem taxonomia paralela. A Cloud API devolve
erros estruturados em JSON (`error.code`, `error.error_subcode`,
`error.message`) — mapear os subcódigos relevantes (token expirado, limite de
mensageria, número não opt-in) para causas de `ChannelError` é parte da
tarefa 1.2.

## Fora de escopo deste change

- Remoção do Evolution API / Baileys do `docker-compose.yml` — só depois que
  a Cloud API estiver operando establemente (change futuro de corte).
- Onboarding formal do número (verificação de negócio, App Review, display
  name) — pré-requisito operacional que o usuário faz no Meta Business
  Manager, fora do código. Este change assume que existe um
  `phone_number_id`, um token de longa duração e um App Secret disponíveis
  para configurar `canal_credenciais`.
- Migração de mensagens/histórico já trocadas via Evolution — não aplicável,
  o histórico já vive em `mensagens` por `contact_id`, independente de
  provedor.
