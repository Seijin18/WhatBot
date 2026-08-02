# Exposição HTTPS do webhook do Instagram

## Why

A Meta exige uma URL HTTPS pública, com certificado válido, para entregar
webhooks. Hoje nada do WhatBot é exposto à internet — Windmill, Evolution
API, Postgres e Redis rodam só na rede local. Este change é infraestrutura
pura: não há comportamento de sistema para especificar, é aceite por
inspeção externa (handshake respondido de fora da rede local), não por teste
automatizado. Por isso não tem `specs/` nem `design.md` — só `tasks.md`.

Detalhe e justificativa completos em
`docs/INSTAGRAM_INTEGRATION_PLAN.md` (Fase 4).

## What Changes

- Túnel ou proxy reverso com domínio próprio e certificado válido, URL
  estável.
- Expor apenas a rota de webhook — Windmill, Evolution API, Postgres e Redis
  continuam inacessíveis pela internet.
- Token de verificação com entropia adequada.
- Procedimento documentado em `DEPLOYMENT.md`.

## Impact

- Specs afetadas: nenhuma (infraestrutura, sem comportamento testável por
  unitário)
- Código alterado: configuração de infraestrutura (túnel/proxy), não código
  Python
- Bloqueia apenas: `instagram-go-live` (que precisa da URL pública para
  assinar o webhook na Meta)
- Não bloqueia nem é bloqueado por nenhum outro change de código — pode
  começar em paralelo desde o primeiro dia, é dependência de calendário
  (DNS, certificado), não de código
