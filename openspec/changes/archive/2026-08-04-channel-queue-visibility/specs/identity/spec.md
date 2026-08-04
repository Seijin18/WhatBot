# Delta: identity

## MODIFIED Requirements

### Requirement: Rótulo legível de contato

Todo contato DEVE ter um rótulo legível para exibição, resolvido com
precedência: nome cadastrado → arroba/handle do canal → identidade externa
crua.

O rótulo DEVE ser puro (sem efeito colateral, sem I/O), para que qualquer
consumidor — fila, notificação, log — possa chamá-lo livremente. DEVE
funcionar mesmo quando `phone` é `NULL`.

A fila e as notificações à secretaria DEVEM usar o rótulo legível junto com o
nome do canal, em vez do identificador externo cru.

#### Scenario: Contato sem nome usa handle

- **WHEN** um contato não tem nome cadastrado mas tem handle do canal
- **THEN** o rótulo legível é o handle

#### Scenario: Contato sem nome nem handle usa identidade externa

- **WHEN** um contato não tem nome nem handle
- **THEN** o rótulo legível é a identidade externa crua

#### Scenario: Fila mostra canal e identificador legível

- **WHEN** um contato de qualquer canal entra na fila ou gera uma notificação
  ao admin
- **THEN** a notificação identifica o canal e o rótulo legível do contato
- **AND** não exibe a identidade externa crua quando um rótulo melhor está
  disponível
