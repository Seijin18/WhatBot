# Delta: admin

## ADDED Requirements

### Requirement: Finalizar atendimento reativa o bot imediatamente

Quando um atendimento é finalizado — comando "atendi o X" (item único),
finalização em lote, ou resposta direta da secretaria via WhatsApp
Business — o bot DEVE voltar a responder o contato imediatamente
(`ia_ativa = TRUE`, `bot_resume_at = NULL`), sem prazo de espera. Não
DEVE haver janela em que o contato fica sem bot e sem atendimento humano
assumido.

#### Scenario: Finalizar um item da fila reativa o bot na hora

- **GIVEN** um contato na fila de atendimento
- **WHEN** o admin envia "atendi o João" (ação `complete`)
- **THEN** `ia_ativa` do João volta a `TRUE` imediatamente
- **AND** `bot_resume_at` fica `NULL`
- **AND** a confirmação ao admin não menciona um prazo de reativação

#### Scenario: Finalização em lote reativa todos os contatos na hora

- **GIVEN** múltiplos contatos na fila de atendimento
- **WHEN** o admin finaliza todos em lote
- **THEN** cada contato finalizado volta com `ia_ativa = TRUE` e
  `bot_resume_at = NULL` imediatamente

#### Scenario: Secretaria responde via WhatsApp Business reativa o bot na hora

- **GIVEN** um contato na fila de atendimento
- **WHEN** a secretaria responde esse contato diretamente pelo WhatsApp
  Business (auto-completar via `handle_staff_outgoing_message`)
- **THEN** o contato sai da fila com `ia_ativa = TRUE` e
  `bot_resume_at = NULL` imediatamente, sem prazo de espera
