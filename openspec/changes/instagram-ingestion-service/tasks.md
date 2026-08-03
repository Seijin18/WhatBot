# Tasks — serviço de ingestão do webhook do Instagram

## 1. Endpoint

- [x] 1.1 `whatbot/ingress.py`: handshake de verificação (`GET`) respondendo
      apenas com o token configurado
      (→ Requirement "Autenticidade e velocidade da ingestão")
- [x] 1.2 Validação de assinatura em tempo constante sobre o corpo bruto
      (→ idem, cenário "Assinatura inválida")
      **Correção pós-critic (BLOQUEADOR 3):** `hmac.compare_digest` levanta
      `TypeError` quando um dos dois valores tem caracteres não-ASCII, o que
      acontecia sempre que um header (`X-Hub-Signature-256` ou
      `hub.verify_token`) trazia um byte >0x7F — Starlette decodifica
      headers como latin-1, então isso era trivialmente acionável e virava
      um 500 não tratado no endpoint exposto e não autenticado. Corrigido:
      `verify_signature`/`verify_handshake` capturam
      `(TypeError, UnicodeError)` e retornam `False` (403), nunca deixam a
      exceção propagar. Testes em
      `tests/test_ingress.py::TestMalformedHeaderIsRejectedNotCrashed`.
- [x] 1.3 Confirmação imediata; processamento fora do ciclo de resposta,
      delegando para `whatbot.main.main(payload)`
      (→ idem, cenário "Confirmação rápida")

## 2. Idempotência

- [x] 2.1 Descarte de evento duplicado pelo `message_id`, usando
      `webhook_eventos`
      (→ Requirement "Idempotência de entrega de webhook")
      **Correção pós-critic (BLOQUEADOR 2):** a versão original gravava o
      evento em `webhook_eventos` *antes* de processar e nunca revertia —
      uma falha no meio do processamento (LLM indisponível, `ChannelError`,
      erro de DB) fazia a reentrega da Meta ser descartada como duplicata
      para sempre, perdendo a mensagem em silêncio. Corrigido: `main()`
      desfaz o registro (`Database.delete_webhook_event`) sempre que o
      processamento não termina em `ok: True` (exceção ou resultado de
      erro), para que a próxima reentrega do mesmo `message_id` seja
      reprocessada. Teste de mutação em
      `tests/test_main_e2e.py::TestIdempotencyRollbackOnFailure` quebra se o
      rollback for removido (verificado manualmente).
      **Correção pós-critic (BLOQUEADOR NOVO — envio duplicado):** o rollback
      acima reage a QUALQUER `ok: False`/exceção de `process_customer_message`,
      inclusive quando o envio real ao cliente (`_router.send_text`) já teve
      sucesso e só um passo de bookkeeping *depois* dele (`_db.save_message`,
      `record_send_result`) falhou — nesse caso a mensagem já chegou ao
      cliente, mas o retorno virava `ok: False`, o registro de idempotência
      era desfeito, e a reentrega do mesmo `message_id` reprocessava do zero
      e reenviava a resposta ao cliente real (2 envios confirmados pelo
      critic). Corrigido em todos os pontos de `process_customer_message`
      onde `send_text` é seguido de código antes do `return` (caminho
      principal de resposta e os dois ramos de `MODEL_UNAVAILABLE_MSG`
      quando o LLM está indisponível): o bookkeeping pós-envio agora roda em
      `try/except` best-effort, logando a falha sem alterar o `ok` do
      retorno. Teste de mutação em
      `tests/test_main_e2e.py::TestNoDuplicateSendWhenPostSendBookkeepingFails`
      quebra se a proteção for removida (verificado manualmente: reversão
      temporária do fix fez o teste falhar com `ok: False` na primeira
      entrega; reaplicado o fix e a suíte completa voltou a passar).
      **Correção pós-critic (BLOQUEADOR NOVO — 4º ponto, caminho de
      handover):** o mesmo padrão de envio-duplicado existia também em
      `whatbot/domain.py::executar_handover_para_secretaria` — o bloco
      pós-`send_to_contact` (`db.save_message`, `db.enroll_handover`,
      `db.get_contact_waiting`, `process_new_handover`,
      `check_long_wait_notifications`) não tinha proteção nenhuma. Corrigido
      com o mesmo padrão de `try/except` best-effort. Teste de mutação em
      `tests/test_main_e2e.py::TestNoDuplicateHandoverSendWhenPostSendBookkeepingFails`
      quebra se a proteção for removida (verificado manualmente).
- [x] 2.2 Limpeza periódica de `webhook_eventos` no job agendado existente

## 3. Infraestrutura

- [x] 3.1 Serviço no `docker-compose.yml` e dependências novas em
      `requirements.txt`
      **Correção pós-critic (MENOR 5):** `DEFAULT_IG_INGRESS_PORT` em
      `whatbot/config.py` estava em `8081`, divergindo de `.env.example` e do
      `docker-compose.yml` (ambos `8090` hardcoded, sem honrar
      `IG_INGRESS_PORT`). Alinhado o default para `8090`; `docker-compose.yml`
      agora usa `${IG_INGRESS_PORT:-8090}` na porta e no comando do
      `uvicorn`.
- [x] 3.2 Scripts operacionais: `scripts/ig_oauth.py`,
      `scripts/ig_refresh_token.py`, `scripts/ig_subscribe_webhook.py`,
      `scripts/ig_health_check.py`, `scripts/ig_simulate_webhook.py`
      **Correção pós-critic (MENOR 6):** em `scripts/ig_refresh_token.py`, se
      a resposta da API de renovação não trouxer `expires_in`, o código
      reaproveitava `credential.expires_at` (que pode já estar perto de
      expirar — motivo de estar renovando), gerando alerta de expiração
      falso mesmo após uma renovação sem erro. Corrigido para usar
      `DEFAULT_IG_TOKEN_LIFETIME_DAYS` (60 dias, documentado em
      `whatbot/config.py`) como default nesse caso, com aviso no log.
- [x] 3.3 `windmill/f/whatbot/refresh_ig_token.py`: job agendado de renovação
      de token
      (→ Requirement "Renovação automática de credencial")
      **Correção pós-critic (MENOR 6):** mesmo ajuste do item 3.2 aplicado
      aqui (job agendado equivalente ao script CLI).
- [x] 3.4 Alertas ao admin: contagem de falhas de envio consecutivas contra
      `IG_ALERT_FAIL_STREAK` (default 5) e tempo desde o último evento de
      webhook contra `IG_ALERT_SILENCE_MINUTES` (default 120), reaproveitando
      `send_admin`. As duas variáveis e seus defaults são definidos aqui;
      `instagram-operability` só documenta runbook e mensagens finais
      (→ Requirement "Alertas de saúde da integração")
      **Correção pós-critic (BLOQUEADOR 1):** a versão original só tinha
      `instagram_health.SendFailureMonitor`, testada isoladamente
      (`tests/test_instagram_health.py`) mas nunca chamada no caminho real de
      envio — o alerta nunca disparava em produção; além disso o contador era
      em memória de processo, que não sobrevive entre execuções no Windmill.
      Corrigido: streak persistido em Postgres
      (`Database.increment_send_fail_streak`/`reset_send_fail_streak`, tabela
      `canal_envio_falhas`) via `instagram_health.record_send_result`,
      chamado do ponto real de envio em
      `whatbot/main.py::process_customer_message` (sucesso e `ChannelError`
      no canal Instagram). Teste de mutação em
      `tests/test_main_e2e.py::TestSendFailureHealthAlertFiresFromTheRealSendPath`
      quebra se a chamada for removida (verificado manualmente).

## 4. Testes

- [x] 4.1 `tests/test_webhook_signature.py`: token inválido recusado,
      assinatura inválida recusada, assinatura válida aceita
- [x] 4.2 Testes do endpoint com `TestClient` (FastAPI), sem rede real:
      confirmação rápida medida, duplicata descartada sem erro
      (→ Requirement "Autenticidade e velocidade da ingestão", "Idempotência
      de entrega de webhook")
- [x] 4.3 Tarefa explícita: asserção de **ordem** (o processamento só é
      invocado depois que a resposta HTTP já foi devolvida), não de duração
      — asserções de tempo de parede são flaky; o que importa é a sequência
      confirmação → processamento, não quantos milissegundos ela leva
      **Reforço pós-critic (IMPORTANTE 4):** o teste original
      (`TestConfirmationHappensBeforeProcessing`) só provava que nada roda
      antes do `return` da função de rota, não a ordenação real no nível de
      transporte ASGI. Adicionado
      `tests/test_ingress.py::TestAsgiTransportOrderOfEvents`, que roda
      `ingress.app(scope, receive, send)` cru e instrumenta `send` para
      capturar a sequência real de eventos
      (`http.response.start`, `http.response.body`, depois o processamento).
- [x] 4.4 Novo caso em `tests/test_main_e2e.py`: segunda entrega do mesmo
      `message_id` não gera segunda resposta — fecha o bloqueio de raiz de
      idempotência de forma automatizada, sem precisar do serviço FastAPI de
      pé
- [x] 4.5 Testes dos alertas de saúde: sequência de falhas de envio dispara
      alerta, ausência prolongada de eventos dispara alerta, sucesso não
      dispara nada
      (→ Requirement "Alertas de saúde da integração")
- [x] 4.6 Suíte completa verde
