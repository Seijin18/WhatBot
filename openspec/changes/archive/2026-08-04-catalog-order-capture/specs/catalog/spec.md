# Delta: catalog

## ADDED Requirements

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
