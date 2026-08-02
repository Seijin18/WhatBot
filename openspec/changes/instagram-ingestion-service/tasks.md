# Tasks — serviço de ingestão do webhook do Instagram

## 1. Endpoint

- [ ] 1.1 `whatbot/ingress.py`: handshake de verificação (`GET`) respondendo
      apenas com o token configurado
      (→ Requirement "Autenticidade e velocidade da ingestão")
- [ ] 1.2 Validação de assinatura em tempo constante sobre o corpo bruto
      (→ idem, cenário "Assinatura inválida")
- [ ] 1.3 Confirmação imediata; processamento fora do ciclo de resposta,
      delegando para `whatbot.main.main(payload)`
      (→ idem, cenário "Confirmação rápida")

## 2. Idempotência

- [ ] 2.1 Descarte de evento duplicado pelo `message_id`, usando
      `webhook_eventos`
      (→ Requirement "Idempotência de entrega de webhook")
- [ ] 2.2 Limpeza periódica de `webhook_eventos` no job agendado existente

## 3. Infraestrutura

- [ ] 3.1 Serviço no `docker-compose.yml` e dependências novas em
      `requirements.txt`
- [ ] 3.2 Scripts operacionais: `scripts/ig_oauth.py`,
      `scripts/ig_refresh_token.py`, `scripts/ig_subscribe_webhook.py`,
      `scripts/ig_health_check.py`, `scripts/ig_simulate_webhook.py`
- [ ] 3.3 `windmill/f/whatbot/refresh_ig_token.py`: job agendado de renovação
      de token
      (→ Requirement "Renovação automática de credencial")
- [ ] 3.4 Alertas ao admin: contagem de falhas de envio consecutivas contra
      `IG_ALERT_FAIL_STREAK` (default 5) e tempo desde o último evento de
      webhook contra `IG_ALERT_SILENCE_MINUTES` (default 120), reaproveitando
      `send_admin`. As duas variáveis e seus defaults são definidos aqui;
      `instagram-operability` só documenta runbook e mensagens finais
      (→ Requirement "Alertas de saúde da integração")

## 4. Testes

- [ ] 4.1 `tests/test_webhook_signature.py`: token inválido recusado,
      assinatura inválida recusada, assinatura válida aceita
- [ ] 4.2 Testes do endpoint com `TestClient` (FastAPI), sem rede real:
      confirmação rápida medida, duplicata descartada sem erro
      (→ Requirement "Autenticidade e velocidade da ingestão", "Idempotência
      de entrega de webhook")
- [ ] 4.3 Tarefa explícita: asserção de **ordem** (o processamento só é
      invocado depois que a resposta HTTP já foi devolvida), não de duração
      — asserções de tempo de parede são flaky; o que importa é a sequência
      confirmação → processamento, não quantos milissegundos ela leva
- [ ] 4.4 Novo caso em `tests/test_main_e2e.py`: segunda entrega do mesmo
      `message_id` não gera segunda resposta — fecha o bloqueio de raiz de
      idempotência de forma automatizada, sem precisar do serviço FastAPI de
      pé
- [ ] 4.5 Testes dos alertas de saúde: sequência de falhas de envio dispara
      alerta, ausência prolongada de eventos dispara alerta, sucesso não
      dispara nada
      (→ Requirement "Alertas de saúde da integração")
- [ ] 4.6 Suíte completa verde
