# Tasks — smoke test real do Instagram Direct

## 0. Pré-condição

- [ ] 0.1 Confirmar suíte completa (`make test`) verde antes de tocar
      infraestrutura real

## 1. Exposição provisória

- [ ] 1.1 Subir túnel HTTPS temporário (cloudflared/ngrok) expondo só a
      porta de `whatbot-ingress` (`IG_INGRESS_PORT`, default 8090) —
      nenhum outro serviço (Postgres, Windmill, Evolution) exposto

## 2. Credenciais e assinatura

- [ ] 2.1 Preencher `.env`: `IG_APP_ID`, `IG_CLIENT_SECRET`, `IG_APP_SECRET`
      (já obtidos pelo usuário no Meta Developer), `IG_WEBHOOK_VERIFY_TOKEN`
      (gerar com entropia adequada), `IG_OAUTH_REDIRECT_URI` apontando para
      a URL do túnel
- [ ] 2.2 Rodar `scripts/ig_oauth.py` — obtém e persiste o token de longa
      duração em `canal_credenciais`
- [ ] 2.3 Rodar `scripts/ig_subscribe_webhook.py` contra a URL pública do
      túnel

## 3. Ligar o cliente em produção

- [ ] 3.1 Registrar `InstagramClient` em `whatbot/main.py::_init_infra()`,
      com `last_inbound_lookup=instagram_last_inbound_lookup(_db)`
      (obrigatório — nunca `_db.get_last_inbound_at` direto)
- [ ] 3.2 `TEST_IGSIDS` com o IGSID de teste do próprio operador (canário
      de 1 pessoa)
- [ ] 3.3 Suíte completa verde após a mudança em `main.py`

## 4. Subir os serviços

- [ ] 4.1 `docker compose --profile instagram up -d` (inclui `db` e
      `whatbot-ingress`) + serviço principal do bot

## 5. Checklist mínimo de smoke test (evidência registrada aqui)

- [ ] 5.1 Mensagem simples do Instagram → resposta chega pelo canal certo
      (evidência: print/log)
- [ ] 5.2 Reentrega do mesmo evento (via `scripts/ig_simulate_webhook.py`
      ou reenvio manual) → não duplica resposta (evidência: log mostrando
      `duplicate_message_id` na segunda entrega)
- [ ] 5.3 Registro em `whatbot/db.py`/`message_log` confirmado com
      `canal=instagram` e identidade (`external_id`/`handle`) corretos,
      não confundido com telefone (evidência: consulta ao banco)
- [ ] 5.4 Se prático sem esperar 24h reais: teste de fora-da-janela
      chamando `send_text` manualmente fora da janela → envio recusado,
      não silenciosamente permitido (evidência: log/erro)

## 6. Fechamento

- [ ] 6.1 Se o checklist passar: registrar aqui o resultado e decidir, com
      base no que foi observado (não a priori), o que de `instagram-webhook-
      exposure`/`instagram-go-live`/`instagram-operability` vale retomar
      a seguir
- [ ] 6.2 Se algo do checklist falhar: registrar o que quebrou como
      pendência concreta, priorizada pelo impacto — vira a próxima tarefa,
      não motivo para voltar aos changes grandes adiados
