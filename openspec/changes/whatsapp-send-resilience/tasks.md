# Tasks — resiliência de envio

## 1. Retry curto no roteador

- [x] 1.1 `ChannelRouter.send_text`: em `ChannelError(retryable=True)`,
      tenta de novo com backoff curto (1s, 3s — total poucos segundos, não
      minutos); erro não-retryable ou esgotar as tentativas propaga
      normalmente
- [x] 1.2 `tests/test_router_retry.py`: sucesso na 2ª tentativa, erro
      não-retryable não tenta de novo, esgota tentativas e propaga o último
      erro, backoff não bloqueia em teste (`time.sleep` mockado). Achado
      durante a implementação: `tests/test_main_e2e.py` e
      `tests/test_campaign.py` já simulavam falha `retryable=True` via
      `FakeClient.raise_error` sem mockar sleep — passou a dormir de
      verdade (~8s extras na suíte) até eu mockar
      `whatbot.channels.router.time.sleep` no `setUp` das duas

## 2. Alerta de saúde multicanal

- [x] 2.1 `whatbot/main.py`: removida a restrição `canal == INSTAGRAM` em
      volta de `record_send_result` — chamado para qualquer canal, nos dois
      pontos (sucesso e falha)
- [x] 2.2 `tests/test_main_e2e.py`: `test_streak_is_tracked_for_whatsapp_too`
      e `test_streak_resets_on_success_for_whatsapp_too`, asserindo direto
      em `db.send_fail_streaks` — não pela entrega do alerta em si, porque
      `ADMIN_CHANNEL = WHATSAPP`: se o WhatsApp é o canal falhando, o
      próprio alerta (que sai por WhatsApp) também falharia. Propriedade
      pré-existente do design ("admin sempre no canal do admin"), não algo
      que este change resolve — só documentado no teste pra não parecer
      esquecimento

## 3. DNS IPv4 preferencial

- [x] 3.1 `whatbot/config.py::force_ipv4_dns()` — monkeypatch de
      `socket.getaddrinfo`, chamado no início de `bootstrap_env()`
      (antes do `try/except` do `dotenv`, pra rodar mesmo se `python-dotenv`
      não estiver instalado)
- [x] 3.2 `tests/test_config_ipv4_dns.py`: filtra pra só `AF_INET`;
      degrada (não quebra) em host só-IPv6; idempotente (segunda chamada
      não repatcheia)

## 4. Suíte

- [x] 4.1 Suíte completa verde — 496 testes, 0.35s (mais rápida que antes:
      os testes que dormiam de verdade por falta de mock agora não dormem)
