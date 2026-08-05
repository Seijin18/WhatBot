# Resiliência de envio: retry curto, alerta multicanal, DNS IPv4

## Why

Durante a validação do `whatsapp-cloud-channel-client`, uma resposta real ao
cliente falhou com `Network is unreachable` ao chamar
`graph.facebook.com` — o mesmo padrão já visto antes com o Gemini
(`generativelanguage.googleapis.com`, via `windmill_worker`): os containers
resolvem DNS com registro AAAA (IPv6), tentam conectar por IPv6, não há rota,
e a falha não cai automaticamente para IPv4 apesar de IPv4 estar disponível e
funcionar (confirmado por teste direto de socket).

Hoje essa falha:
1. Não tem retry nenhum no caminho de conversa em tempo real — só campanhas
   em massa (`disparo_mensagens`) têm retry, via `CAMPAIGN_MAX_RETRIES`.
2. Não gera alerta pro admin quando o canal é WhatsApp — `record_send_result`
   (`whatbot/instagram_health.py`) só está ligado para `canal == INSTAGRAM`
   em `whatbot/main.py`, apesar de `canal_envio_falhas` já ser genérico por
   `canal` desde sempre.
3. A causa-raiz (resolução DNS preferindo IPv6 sem rota) não tem mitigação —
   `evolution-api` (Node) já resolve isso com
   `NODE_OPTIONS=--dns-result-order=ipv4first`; não há equivalente para os
   processos Python (`whatbot_ingress`, jobs do Windmill).

## What Changes

- `whatbot/channels/router.py`: `ChannelRouter.send_text` ganha retry curto
  (poucos segundos de backoff total) quando o cliente levanta
  `ChannelError(retryable=True)` — cobre os três clientes (`Evolution`,
  `Instagram`, `WhatsAppCloudClient`) num único ponto, sem duplicar lógica
  em cada um. Erro não-retryable continua propagando na primeira tentativa,
  sem mudança.
- `whatbot/main.py`: `record_send_result` deixa de ser exclusivo do
  Instagram — chamado para qualquer canal após o envio (sucesso ou falha),
  reaproveitando a tabela `canal_envio_falhas` e o limiar já configurável
  (`IG_ALERT_FAIL_STREAK`, reaproveitado como limiar genérico — não cria
  variável nova).
- `whatbot/config.py`: `force_ipv4_dns()`, chamada de dentro de
  `bootstrap_env()` — monkeypatch de `socket.getaddrinfo` filtrando só
  registros IPv4, aplicado uma vez por processo. Afeta `requests` (Evolution,
  Instagram, WhatsApp Cloud) e `httpx`/`httpcore` (Gemini) igualmente, por
  atuar na camada mais baixa (stdlib), não em cada biblioteca HTTP
  separadamente.

## Impact

- Specs afetadas: `channels` (retry), nenhuma nova capability — é
  fortalecimento de comportamento já especificado ("Falha de transporte é
  tipada"), não um requirement novo de produto.
- Código: `whatbot/channels/router.py`, `whatbot/main.py`,
  `whatbot/config.py`
- Testes novos/estendidos: `tests/test_router_retry.py` (novo),
  `tests/test_main_e2e.py` ou teste dedicado para `record_send_result`
  multicanal, `tests/test_config.py` (ou onde já existir) para
  `force_ipv4_dns`
- Não bloqueia nem depende de nenhum change ativo.
- Fora de escopo: retry para campanhas em massa (já tem o próprio mecanismo,
  mais longo, adequado ao caso de uso); alerta de silêncio de webhook para
  WhatsApp (`IG_ALERT_SILENCE_MINUTES` — só faz sentido pra canais com
  webhook contínuo tipo Instagram/WhatsApp Cloud, mas é uma extensão
  separada, não pedida aqui).
