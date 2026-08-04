# Delta: catalog

## ADDED Requirements

### Requirement: Catálogo sincronizado periodicamente

O sistema DEVE manter uma cópia local do catálogo de produtos do WhatsApp
Business, atualizada periodicamente a partir da Evolution API, para
permitir resolução de `productId` para nome e preço sem depender de uma
chamada de rede síncrona durante o atendimento.

#### Scenario: Sincronização atualiza produtos existentes

- **WHEN** o job de sincronização roda e a Evolution API retorna o catálogo
  atual
- **THEN** os produtos já conhecidos são atualizados (nome, preço,
  disponibilidade)
- **AND** produtos novos no catálogo remoto passam a existir localmente

#### Scenario: Falha de sincronização não derruba o sistema

- **WHEN** a chamada à Evolution API para buscar o catálogo falha (rede,
  timeout, erro HTTP)
- **THEN** o cache local permanece com os dados da última sincronização
  bem-sucedida
- **AND** nenhuma mensagem de cliente é bloqueada por essa falha

### Requirement: Resolução de itens de pedido por id

O sistema DEVE conseguir resolver uma lista de `productId`/`retailerId`
para nome e preço a partir do catálogo sincronizado localmente.

#### Scenario: Item conhecido é resolvido

- **WHEN** um `productId` presente no catálogo sincronizado é consultado
- **THEN** o sistema retorna nome e preço desse produto

#### Scenario: Item desconhecido não quebra a resolução dos demais

- **WHEN** uma lista de `productId` inclui um id que não existe no cache
  local
- **THEN** os demais ids da lista são resolvidos normalmente
- **AND** o id desconhecido é omitido do resultado, sem levantar erro
