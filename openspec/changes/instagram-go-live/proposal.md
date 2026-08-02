# Lançamento controlado do Instagram em conta real

## Why

Todos os changes anteriores (`identity-multichannel`,
`channel-queue-visibility`, `instagram-messaging-window`,
`instagram-channel-client`, `instagram-webhook-exposure`,
`instagram-ingestion-service`) entregam código testável isoladamente, mas
nenhum deles liga a conta real. Este change é o único que toca produção de
verdade: registra o cliente no roteador, conecta a conta real, assina o
webhook na Meta, e conduz a homologação e o canário.

Não pode ser revertido por rollback de banco (a conta já estará conectada à
Meta), por isso fica por último — tudo mais precisa estar verde antes.

## What Changes

- Pré-requisitos da Meta (podem começar em paralelo desde o dia 1, mas
  bloqueiam só este change): conta profissional com mensagens liberadas em
  Ferramentas Conectadas, App Business com produto Instagram na variante
  Instagram Login, App ID/App Secret guardados, escopos
  `instagram_business_basic` e `instagram_business_manage_messages`, fluxo de
  token até o token de longa duração, assinatura do campo `messages`.
- Registrar `whatbot/channels/instagram.py` no `ChannelRouter`.
- `TEST_IGSIDS`: lista de contas de teste do Instagram, populando o
  mecanismo de filtro por canal já definido em `identity-multichannel`
  (requirement "Filtro de teste por canal") — equivalente ao já existente
  `TEST_PHONES` do WhatsApp.
- Roteiro de homologação de 14 casos executado em conta real, cada um com
  data, executor e evidência.
- Canário de 3 dias restrito à equipe, depois abertura gradual.

## Impact

- Specs afetadas: `identity` (MODIFIED — configura o mecanismo de filtro de
  teste já definido em `identity-multichannel` para o Instagram, não cria
  requirement novo; ver `specs/identity/spec.md`)
- Código alterado: `whatbot/channels/__init__.py` ou onde o roteador é
  montado (registro do cliente novo), variáveis de ambiente
- Sem teste automatizado novo — usa a suíte já verde (herdada de todos os
  changes anteriores) como pré-condição antes de ir para a homologação
  manual. Os 14 casos de homologação real são complementares, não
  substitutos, do teste E2E automatizado em `tests/test_main_e2e.py`.
- Bloqueado por: `identity-multichannel`, `channel-queue-visibility`,
  `instagram-messaging-window`, `instagram-channel-client`,
  `instagram-webhook-exposure`, `instagram-ingestion-service` — todos
  precisam estar prontos antes de ligar a conta real
