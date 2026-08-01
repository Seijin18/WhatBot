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

`human_agent` sinaliza entrega sob permissão de atendimento humano em canais que
impõem janela de mensageria. Canais sem janela DEVEM aceitar e ignorar o
parâmetro.

#### Scenario: Canal sem janela de mensageria ignora human_agent

- **WHEN** `send_text` é chamado com `human_agent=True` num cliente WhatsApp
- **THEN** a mensagem é enviada normalmente, sem alteração de payload

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

#### Scenario: Resposta segue o canal de entrada

- **WHEN** uma mensagem chega pelo canal X e o bot gera uma resposta
- **THEN** a resposta é entregue pelo cliente do canal X

### Requirement: Admin sempre no canal do admin

Notificações à secretaria — novo item na fila, espera prolongada, resumo diário,
reativação automática, confirmação de comando administrativo — DEVEM ser
entregues no canal de admin (`whatsapp`), qualquer que seja o canal do cliente
que originou o evento.

A secretaria não deve precisar trocar de ferramenta de trabalho conforme o canal
do cliente.

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

Quando o alvo for um cliente puro, os argumentos específicos de roteamento
(`canal`, `human_agent`) DEVEM ser descartados sem erro.

#### Scenario: Helper recebe cliente legado

- **WHEN** `send_to_contact` recebe um cliente sem suporte a `human_agent`
- **THEN** a mensagem é enviada com os argumentos que o cliente aceita
- **AND** nenhuma exceção é levantada
