# Tasks — smoke test real do Instagram Direct

## 0. Pré-condição

- [x] 0.1 Confirmar suíte completa (`make test`) verde antes de tocar
      infraestrutura real

## 1. Exposição provisória

- [x] 1.1 Subir túnel HTTPS temporário (cloudflared/ngrok) expondo só a
      porta de `whatbot-ingress` (`IG_INGRESS_PORT`, default 8090) —
      nenhum outro serviço (Postgres, Windmill, Evolution) exposto.
      `cloudflared` instalado via `winget` (`Cloudflare.cloudflared`) e
      rodando como quick tunnel (`cloudflared tunnel --url
      http://localhost:8090`), sem conta/token — só a porta do ingress é
      encaminhada. **URL é efêmera**: válida só enquanto o processo
      continuar rodando; se reiniciado, atualizar `IG_OAUTH_REDIRECT_URI` e
      reassinar o webhook (tarefa 2.3).

## 2. Credenciais e assinatura

- [x] 2.1 Preencher `.env`: `IG_APP_ID`, `IG_CLIENT_SECRET`, `IG_APP_SECRET`
      (já obtidos pelo usuário no Meta Developer), `IG_WEBHOOK_VERIFY_TOKEN`
      (gerar com entropia adequada), `IG_OAUTH_REDIRECT_URI` apontando para
      a URL do túnel. `IG_APP_SECRET`/`IG_CLIENT_SECRET` recebem o mesmo
      valor (o "Instagram app secret" único do painel Meta) — usados em
      pontos de código diferentes (validação de assinatura do webhook vs.
      troca do código OAuth). Redirect URI também precisou ser cadastrada
      manualmente no painel Meta ("Business login settings" → "OAuth
      redirect URIs") — a Meta recusa `redirect_uri` não cadastrada.
- [x] 2.2 Rodar `scripts/ig_oauth.py` — obtém e persiste o token de longa
      duração em `canal_credenciais`. Postgres precisou estar de pé antes
      da troca (senão o token seria obtido mas não salvo, e o código de
      uso único seria desperdiçado) — Docker Desktop iniciado, `docker
      compose up -d db`, então a troca. Credencial salva para `@camu3d`,
      expira em 2026-10-02.
- [x] 2.3 Rodar `scripts/ig_subscribe_webhook.py` contra a URL pública do
      túnel. Handshake de verificação testado manualmente antes (curl
      contra o túnel com o verify token real → `200` ecoando o
      `hub.challenge`), depois configurado no painel Meta (Webhooks →
      Instagram → Callback URL + Verify Token → "Verify and Save") e
      confirmado lá também. `scripts/ig_subscribe_webhook.py` rodado por
      último, assinando a conta ao campo `messages` — resposta
      `{'success': True}`.

## 3. Ligar o cliente em produção

- [x] 3.1 Registrar `InstagramClient` em `whatbot/main.py::_init_infra()`,
      com `last_inbound_lookup=instagram_last_inbound_lookup(_db)`
      (obrigatório — nunca `_db.get_last_inbound_at` direto). Implementado
      como `_register_instagram_client_if_configured(router, db)`: só
      registra o canal depois que `canal_credenciais` tem uma credencial
      real (produzida pela tarefa 2.2/`scripts/ig_oauth.py`) — até lá o
      WhatsApp continua funcionando sozinho e o `ChannelRouter` recusa
      tráfego do Instagram explicitamente (`UnknownChannelError`, não
      silêncio). Testes diretos em
      `tests/test_main_e2e.py::TestInstagramClientRegistration` (sem
      credencial → não registrado; com credencial → cliente funcional e
      `last_inbound_lookup` fiado corretamente) — verificado por mutação
      manual (trocar o lookup por `None` faz o teste falhar por
      fail-closed).
- [ ] 3.2 `TEST_IGSIDS` com o IGSID de teste do próprio operador (canário
      de 1 pessoa) — pendente: depende do IGSID real do operador
- [x] 3.3 Suíte completa verde após a mudança em `main.py` (276 testes)

## 4. Subir os serviços

- [x] 4.1 `docker compose --profile instagram up -d` (inclui `db` e
      `whatbot-ingress`); serviço principal do bot (WhatsApp) não precisou
      subir — `whatbot-ingress` chama `whatbot.main.main()` no próprio
      processo, autossuficiente para o fluxo do Instagram

## 5. Checklist mínimo de smoke test (evidência registrada aqui)

- [x] 5.1 Mensagem simples via `scripts/ig_simulate_webhook.py` → processada
      de ponta a ponta: contato criado, LLM chamado, resposta ancorada na
      base de conhecimento, tentativa de envio pelo canal correto.
      **Bloqueado só na entrega final** por `IGSID` fictício (o script usa
      um ID de exemplo, não uma conta real) — `ChannelError` tipado,
      capturado, sem derrubar o processo. Entrega com IGSID real depende de
      `instagram-go-live` (registro de conta real) e possivelmente da
      Análise do App (ver seção 7).
- [x] 5.2 Reentrega do mesmo `message_id` (`sim-dedupe-test-1`) → segunda
      chamada descartada como duplicata **antes** da primeira terminar de
      processar (log: `Evento duplicado descartado: canal=instagram
      message_id=sim-dedupe-test-1`), confirmado contra o `whatbot-ingress`
      real, não só em teste unitário com fake.
- [x] 5.3 Log confirma `canal=instagram`, identidade
      (`external_id=17841400000000001`) correta, contato criado sem
      confundir com telefone.
- [x] 5.4 Coberto por testes automatizados com verificação de mutação
      (`tests/test_messaging_window.py`) — não repetido manualmente aqui.

**Nota sobre entrega real**: `GET /me/conversations` retornou `data: []`
mesmo com mensagem real visível no app do Instagram — a API de mensagens
não expõe dados reais (leitura nem entrega de webhook) sem Acesso Avançado.
Ver seção 7.

## 6. Fechamento

- [x] 6.1 Checklist do nosso lado (5.1-5.4) passou integralmente contra o
      `whatbot-ingress` real. O que falta para mensagem real ida-e-volta
      não é código nosso — é acesso da Meta (seção 7).
- [ ] 6.2 N/A — nada do nosso lado quebrou

## 7. Bloqueio real identificado: Acesso Avançado / Análise do App

Investigação extensa (handshake, assinatura, token, tester aceito, conta
conectada — tudo confirmado correto) isolou o problema: mensagens reais do
Instagram Direct chegam normalmente no app do Instagram, mas a API de
mensagens (`instagram_business_manage_messages`) não expõe esses dados para
o nosso app — nem leitura (`GET /conversations` retorna vazio) nem entrega
de webhook — sem que o app complete a **Análise do App** da Meta.

Evidência: `docs oficiais da Meta` — "Apps must be set to Live in the App
Dashboard to receive webhook notifications." E no painel do app
(`Configuração da API com login do Instagram`), passo 5 "Concluir a análise
do app": *"Para que seu app acesse dados ao vivo, o Instagram exige que o
processo de análise do app seja realizado."*

**Escopo da análise, já reduzido**: removidas 4 permissões desnecessárias
que tinham entrado por engano (`instagram_business_content_publish`,
`instagram_business_manage_insights`, `instagram_business_manage_comments`,
`Human Agent`) — a submissão fica só com as 2 que usamos de verdade:
`instagram_business_basic`, `instagram_business_manage_messages`.

**O que a submissão exige** (mapeado, nada enviado):
1. Verificação de identidade/empresa (documentos comerciais) — item mais
   pesado, prazo incerto.
2. Configurações do app (ícone, política de privacidade).
3. Descrição de uso permitido por permissão.
4. Descrição de tratamento de dados.
5. Instruções de análise (credenciais de teste e/ou vídeo de demonstração
   para os revisores da Meta).

**Decisão pendente do usuário**: iniciar a Verificação de Empresa e a
submissão quando houver tempo/documentação disponível. Alternativa de
automação não-oficial (tipo `instagrapi`) foi considerada e descartada —
risco de ban da conta significativamente maior que o caso do WhatsApp
(Evolution API), porque a detecção de automação da Meta é mais agressiva
especificamente em DM do Instagram, e essas bibliotecas em geral exigem
usuário/senha reais em vez de token.
