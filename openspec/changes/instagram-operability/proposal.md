# Documentação e operação do Instagram

## Why

Uma integração com credencial que expira, webhook externo e um canal a mais
para a secretaria monitorar não sobrevive sem runbook, alertas e
treinamento. O risco número um do projeto, segundo
`docs/INSTAGRAM_INTEGRATION_PLAN.md`, é organizacional: a secretaria
responder DM pelo Instagram enquanto recebe o aviso pelo WhatsApp é uma
mudança de hábito de trabalho, não um problema técnico —
`channel-queue-visibility` mitiga a parte técnica (mostrar o canal), este
change cobre a parte de processo (treinamento, runbook, alertas).

## What Changes

- `README.md`, `DEPLOYMENT.md` e `.env.example` atualizados com o fluxo do
  Instagram.
- Atalhos de operação no `Makefile` (espelhando os já existentes para
  WhatsApp).
- Runbook de renovação de credencial e de queda da integração.
- Alertas ao admin: sequência de falhas de envio, ausência prolongada de
  eventos (a renovação de credencial em si já está coberta pelo requirement
  "Renovação automática de credencial" de `instagram-ingestion-service`; não
  duplicar aqui — só a parte de alerta que ainda não estiver coberta lá).
- Rollback documentado e testado uma vez.
- Secretaria treinada no fluxo.

## Impact

- Specs afetadas: nenhuma nova — o requirement "Alertas de saúde da
  integração" já é especificado e testado em `instagram-ingestion-service`;
  este change só entrega a parte operacional (runbook, thresholds
  documentados, mensagens finais).
- Código alterado: `README.md`, `DEPLOYMENT.md`, `.env.example`, `Makefile`
- Bloqueado por: `instagram-ingestion-service` (os alertas dependem de
  código já existir); as partes de documentação podem ser escritas em
  paralelo com `instagram-go-live`

## Adiado — retomar após smoke test

Execução substituída, para a primeira validação real, por
`instagram-live-smoke-test`. O código dos alertas de saúde já existe e
está testado (`whatbot/instagram_health.py`, chamado do caminho real de
envio) — o que falta aqui é só a camada operacional (runbook, treinamento
da secretaria, rollback testado), que só vale a pena formalizar depois que
o smoke test confirmar o esqueleto funcionando. Retomar quando houver uso
real (mesmo que pequeno) o suficiente para o runbook refletir problemas
reais, não hipotéticos.
