# Delta: admin

## ADDED Requirements

### Requirement: Simular como o próprio admin usa o fluxo real

Quando o admin usa `#simular` (sessão persistente ou de um turno só) com o
número simulado igual ao próprio número do admin, o sistema DEVE processar
a mensagem pelo fluxo real de cliente — persistindo em `mensagens` e
`session_state`, e enviando a resposta de verdade pelo canal — em vez do
sandbox que não persiste nada. Simular como qualquer outro número DEVE
continuar sandboxed, sem tocar dados reais.

#### Scenario: Simular como o próprio número persiste e responde de verdade

- **WHEN** o admin simula como cliente usando o próprio número
- **THEN** a mensagem do turno é salva no histórico do contato
- **AND** a resposta do bot é enviada de verdade pelo canal, não apenas
  decorada e mandada de volta ao admin

#### Scenario: Simular como outro número continua sandboxed

- **WHEN** o admin simula como cliente usando um número diferente do
  próprio
- **THEN** nada é persistido no histórico real desse outro contato
- **AND** a resposta continua sendo apenas decorada e enviada ao admin,
  nunca ao número simulado
