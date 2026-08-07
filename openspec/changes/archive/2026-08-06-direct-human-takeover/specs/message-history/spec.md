# Delta: message-history

## ADDED Requirements

### Requirement: Assumir atendimento direto pela API administrativa

O sistema DEVE permitir que um admin coloque um contato em atendimento
humano imediatamente através da API administrativa, sem depender do bot
ter detectado um pedido de handover primeiro.

#### Scenario: Contato em modo bot é assumido diretamente

- **WHEN** um admin chama a rota de assumir atendimento para um contato com
  `ia_ativa = TRUE`
- **THEN** o contato passa a `ia_ativa = FALSE`, com `handover_at`
  registrado e `assumido_por` já preenchido pelo admin que assumiu
- **AND** o bot para de responder normalmente a esse contato, mesmo sem
  ele ter pedido atendimento humano

#### Scenario: Assumir um contato já em atendimento humano não é erro

- **WHEN** um admin chama a rota de assumir atendimento para um contato que
  já está com `ia_ativa = FALSE`
- **THEN** a resposta indica sucesso, sem duplicar o registro de handover
