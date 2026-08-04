# catalog Specification

## Purpose
TBD - created by archiving change catalog-order-capture. Update Purpose after archive.
## Requirements
### Requirement: Pedido do catálogo nunca é descartado

Uma mensagem recebida do WhatsApp cujo conteúdo seja um pedido feito a
partir do catálogo (`orderMessage`) DEVE sempre resultar em uma mensagem
processável pelo sistema, mesmo quando o payload não traz itens
identificáveis. O sistema NÃO DEVE descartar silenciosamente uma mensagem
só porque o texto livre extraído dela está vazio.

#### Scenario: Pedido completo (Android) é capturado

- **WHEN** o webhook da Evolution API entrega um `orderMessage` com itens
  contendo `productId`
- **THEN** o payload processado pelo sistema contém os itens do pedido
- **AND** a mensagem não é descartada por falta de texto livre

#### Scenario: Pedido sem itens identificáveis (iOS) ainda é capturado

- **WHEN** o webhook da Evolution API entrega um `orderMessage` sem
  `productId`/`retailerId` em nenhum item
- **THEN** o payload processado pelo sistema marca o pedido como não
  identificável, mas ainda assim não é descartado
- **AND** o pedido é tratado com a mesma prioridade que um pedido completo

### Requirement: Pedido do catálogo dispara handover automático

Todo pedido real recebido do catálogo do WhatsApp DEVE resultar em
handover automático para atendimento humano, independentemente de os itens
serem identificáveis ou não.

#### Scenario: Pedido dispara handover com prioridade máxima

- **WHEN** um contato envia um pedido pelo catálogo do WhatsApp
- **THEN** o contato entra na fila de handover com prioridade 1
- **AND** o handover acontece sem exigir nenhuma outra ação do cliente

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

