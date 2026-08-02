# Capability: channels — roteamento de saída multicanal

## Purpose

Isolar o envio de mensagens atrás de um contrato único, para que o núcleo do bot
(IA, base de conhecimento, fila, handover) não conheça nenhum canal concreto.
Um cliente é sempre respondido no canal em que falou; a secretaria é sempre
notificada no canal dela, independente da origem.

## Requirements

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

### Requirement: Resolução de cliente por canal

O `ChannelRouter` DEVE resolver o cliente de saída pelo nome do canal, registrando
clientes pelo atributo `canal` de cada um.

Quando nenhum canal for informado, o roteador DEVE usar o canal padrão
(`whatsapp`).

#### Scenario: Canal não informado cai no padrão

- **WHEN** `send_text` é chamado sem `canal`
- **THEN** a mensagem sai pelo cliente do canal padrão

#### Scenario: Canal sem cliente registrado falha explicitamente

- **WHEN** `send_text` é chamado com um canal que não tem cliente registrado
- **THEN** `UnknownChannelError` é levantada, nomeando o canal pedido e os
  canais registrados
- **AND** nenhuma mensagem é enviada por nenhum cliente

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

### Requirement: Admin sempre no canal do admin

Notificações à secretaria — novo item na fila, espera prolongada, resumo diário,
reativação automática, confirmação de comando administrativo — DEVEM ser
entregues no canal de admin (`whatsapp`), qualquer que seja o canal do cliente
que originou o evento.

A secretaria não deve precisar trocar de ferramenta de trabalho conforme o canal
do cliente.

O conteúdo exibido nessas notificações (rótulo legível do contato, indicação
de canal) é governado pela capability `identity` — ver requisito "Rótulo
legível de contato" em `openspec/specs/identity/spec.md` — este requisito
cobre só o roteamento da notificação, não o texto.

#### Scenario: Handover de cliente em outro canal notifica admin no WhatsApp

- **WHEN** um cliente de um canal não-WhatsApp pede atendimento humano
- **THEN** o cliente recebe a confirmação no canal dele
- **AND** a secretaria recebe a notificação pelo WhatsApp

### Requirement: Nenhum envio direto por cliente concreto

Os módulos de domínio (`main`, `domain`, `queue`, `admin`) NÃO DEVEM segurar nem
chamar um cliente de canal concreto. Todo envio DEVE passar pelo `ChannelRouter`
ou pelos helpers `send_admin` / `send_to_contact`.

#### Scenario: Auditoria estática

- **WHEN** se busca por chamadas diretas a um cliente concreto nesses módulos
- **THEN** não há nenhuma ocorrência

### Requirement: Compatibilidade com cliente único

Os helpers de despacho DEVEM aceitar tanto um `ChannelRouter` quanto um cliente
de canal isolado, para que código legado e testes possam injetar um cliente puro.

A detecção DEVE ser por capacidade — a presença do método de roteamento — e não
por tipo concreto, de modo que qualquer objeto que implemente o roteamento
preserve `canal` e `human_agent`.

Quando o alvo for um cliente puro, os argumentos específicos de roteamento
(`canal`, `human_agent`) DEVEM ser descartados sem erro.

#### Scenario: Helper recebe cliente legado

- **WHEN** `send_to_contact` recebe um cliente sem suporte a `human_agent`
- **THEN** a mensagem é enviada com os argumentos que o cliente aceita
- **AND** nenhuma exceção é levantada

#### Scenario: Helper recebe roteador que não é o tipo concreto

- **WHEN** `send_to_contact` recebe um objeto que roteia por canal sem ser
  instância da classe concreta
- **THEN** `canal` e `human_agent` são preservados na entrega
