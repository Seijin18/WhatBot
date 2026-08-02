# Tasks — lançamento controlado do Instagram em conta real

## 0. Pré-requisitos da Meta (sem código, pode começar já — envolve terceiros)

- [ ] 0.1 Conta do Instagram como profissional, com acesso a mensagens
      liberado em Ferramentas Conectadas (sem isso os webhooks simplesmente
      não chegam — é a falha silenciosa mais comum)
- [ ] 0.2 App Business criado, produto Instagram adicionado na variante com
      Instagram Login; guardar App ID e App Secret
- [ ] 0.3 Escopos `instagram_business_basic` e
      `instagram_business_manage_messages`
- [ ] 0.4 Fluxo de token executado até o token de longa duração
- [ ] 0.5 Assinatura do campo `messages` no webhook
- [ ] 0.6 Checkpoint de App Review (esperado desnecessário sob Standard
      Access — ver `instagram-channel-client/design.md`)

## 1. Integração ponta a ponta

- [ ] 1.1 Registrar `whatbot/channels/instagram.py` no `ChannelRouter` —
      montar o `InstagramClient` com
      `last_inbound_lookup=instagram_last_inbound_lookup(_db)` (helper de
      `whatbot/channels/instagram.py`), nunca `_db.get_last_inbound_at`
      direto: sem `canal=INSTAGRAM` fixado, o client fica fail-closed 100% do
      tempo (ver `instagram-messaging-window` Importante 5)
- [ ] 1.2 Conectar a conta real e assinar o webhook (depende de
      `instagram-webhook-exposure` e `instagram-ingestion-service` prontos)
- [ ] 1.3 `TEST_IGSIDS` populado com as contas de teste reais, usando o
      mecanismo já definido em `identity-multichannel`
      (→ Requirement "Filtro de teste por canal")

## 2. Homologação e canário

- [ ] 2.1 Roteiro de homologação de 14 casos executado em conta real, cada
      caso com data, executor e evidência (complementar ao teste E2E
      automatizado, não substituto — ver `tests/test_main_e2e.py`)
- [ ] 2.2 Canário de 3 dias restrito à equipe, depois abertura gradual
      (→ Requirement "Filtro de teste por canal")

## 3. Pré-condição

- [ ] 3.1 Confirmar suíte completa (`make test`) verde antes de iniciar a
      homologação em conta real
