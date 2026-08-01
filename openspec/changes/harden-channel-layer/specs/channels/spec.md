# Delta: channels

## ADDED Requirements

### Requirement: Canal desconhecido é rejeitado na borda

Um nome de canal que não esteja em `SUPPORTED_CHANNELS` DEVE ser rejeitado no
ponto de entrada — na normalização do payload recebido — e não apenas na hora do
envio.

A rejeição DEVE nomear o canal recusado.

#### Scenario: Payload chega com canal não suportado

- **WHEN** um payload de entrada declara um canal fora de `SUPPORTED_CHANNELS`
- **THEN** o processamento é interrompido na borda, com erro que nomeia o canal
- **AND** nenhuma consulta ao banco e nenhuma chamada ao modelo acontece

#### Scenario: Canal ausente ou vazio continua caindo no padrão

- **WHEN** o payload não traz canal, ou traz string vazia ou só espaços
- **THEN** o canal resolvido é o padrão (`whatsapp`), sem erro

### Requirement: Falha de transporte é tipada

Um cliente de canal DEVE sinalizar falha de entrega com `ChannelError`,
identificando o canal e informando em `retryable` se a operação pode ser
repetida.

Erros crus da biblioteca HTTP NÃO DEVEM vazar para os módulos de domínio, que
não conhecem o transporte de nenhum canal.

#### Scenario: Falha de rede ao enviar

- **WHEN** o transporte falha ao entregar uma mensagem
- **THEN** `ChannelError` é levantada, identificando o canal
- **AND** o envio é registrado no log de saída como falho

### Requirement: Entrada normalizada em formato único

Os parsers de webhook DEVEM produzir `InboundMessage` e derivar o payload de
processamento dele, para que cada canal novo tenha um único formato de entrada a
implementar.

A resolução do canal em `InboundMessage` DEVE ser insensível a caixa e a espaços
em volta.

#### Scenario: Parser de WhatsApp produz InboundMessage

- **WHEN** um webhook de mensagem de cliente é recebido
- **THEN** um `InboundMessage` é construído com o canal e a identidade externa
- **AND** o payload derivado preserva o formato que o processamento já consome

## MODIFIED Requirements

### Requirement: Contrato único de canal

Todo cliente de canal DEVE expor `canal: str` e um método `send_text` com a
assinatura definida pelo protocolo `ChannelClient`, aceitando os keyword-only
`source`, `contact_id`, `simulated` e `human_agent`.

O nome do primeiro parâmetro DEVE ser o mesmo do protocolo em toda
implementação, de modo que a chamada por keyword funcione em qualquer canal.

`human_agent` sinaliza entrega sob permissão de atendimento humano em canais que
impõem janela de mensageria. Canais sem janela DEVEM aceitar e ignorar o
parâmetro.

#### Scenario: Canal sem janela de mensageria ignora human_agent

- **WHEN** `send_text` é chamado com `human_agent=True` num cliente WhatsApp
- **THEN** a mensagem é enviada normalmente, sem alteração de payload

#### Scenario: Chamada por keyword funciona em qualquer cliente

- **WHEN** `send_text` é chamado nomeando o destinatário por keyword
- **THEN** a chamada é aceita por qualquer implementação do protocolo

### Requirement: Compatibilidade com cliente único

Os helpers de despacho DEVEM aceitar tanto um `ChannelRouter` quanto um cliente
de canal isolado, para que código legado e testes possam injetar um cliente puro.

A detecção DEVE ser por capacidade — a presença do método de roteamento — e não
por tipo concreto, de modo que qualquer objeto que implemente o roteamento
preserve `canal` e `human_agent`.

Quando o alvo for um cliente puro, os argumentos específicos de roteamento
DEVEM ser descartados sem erro.

#### Scenario: Helper recebe cliente legado

- **WHEN** `send_to_contact` recebe um cliente sem suporte a `human_agent`
- **THEN** a mensagem é enviada com os argumentos que o cliente aceita
- **AND** nenhuma exceção é levantada

#### Scenario: Helper recebe roteador que não é o tipo concreto

- **WHEN** `send_to_contact` recebe um objeto que roteia por canal sem ser
  instância da classe concreta
- **THEN** `canal` e `human_agent` são preservados na entrega

### Requirement: Cliente responde no próprio canal

Toda mensagem dirigida a um cliente — resposta do bot, aviso de indisponibilidade
do modelo, confirmação de handover — DEVE ser entregue no canal em que a
mensagem de entrada chegou.

Isso vale também para mensagens geradas em simulação administrativa: a simulação
DEVE preservar o canal do contato simulado.

#### Scenario: Resposta segue o canal de entrada

- **WHEN** uma mensagem chega pelo canal X e o bot gera uma resposta
- **THEN** a resposta é entregue pelo cliente do canal X

#### Scenario: Simulação de contato preserva o canal

- **WHEN** um admin simula uma conversa como um contato de outro canal
- **THEN** a resposta simulada é resolvida no canal daquele contato
- **AND** o retorno da simulação chega ao admin pelo canal de admin
