# Delta: instagram

## ADDED Requirements

### Requirement: Janela de mensageria de 24 horas

Antes de qualquer envio pelo Instagram, a janela de mensageria DEVE ser
verificada contra o último recebimento daquele contato (`last_inbound_at`).

- Dentro de 24 h: envio normal.
- Fora de 24 h, em atendimento humano: envio sob permissão de atendimento
  humano (`human_agent=True`), válida por até 7 dias.
- Fora de 7 dias, ou fora de 24h sem atendimento humano: o envio NÃO DEVE
  acontecer; a tentativa é registrada e devolve falha identificada.

Reativação automática do bot (encerramento de handover) NÃO DEVE gerar
mensagem proativa — o bot só volta a responder na próxima mensagem do
cliente.

#### Scenario: Mensagem automática dentro da janela

- **WHEN** o bot responde a um contato que escreveu há menos de 24h
- **THEN** a mensagem é enviada normalmente

#### Scenario: Mensagem automática fora da janela

- **WHEN** o bot tentaria enviar automaticamente a um contato silencioso há
  mais de 24h
- **THEN** nada é enviado
- **AND** o resultado identifica a janela como motivo da recusa

#### Scenario: Atendimento humano fora da janela de 24h

- **WHEN** a secretaria responde a um contato silencioso há mais de 24h e
  menos de 7 dias
- **THEN** a mensagem é entregue sob a permissão de atendimento humano

#### Scenario: Fora da janela de 7 dias mesmo com atendimento humano

- **WHEN** a secretaria tenta responder a um contato silencioso há mais de 7
  dias
- **THEN** o envio é recusado, com falha identificada

#### Scenario: Reativação automática não é proativa

- **WHEN** um handover é encerrado e o bot volta a responder automaticamente
- **THEN** nenhuma mensagem é enviada até que o cliente escreva de novo

### Requirement: Notificação de fila informa prazo de resposta

Quando o canal do contato impõe janela de mensageria, a notificação de fila
(rótulo definido em `channel-queue-visibility`) DEVE informar o prazo restante
de resposta.

#### Scenario: Novo item do Instagram informa prazo

- **WHEN** um contato do Instagram entra na fila
- **THEN** a notificação ao admin informa o prazo de resposta (dentro de
  24h, ou até quando a janela de atendimento humano de 7 dias expira)
