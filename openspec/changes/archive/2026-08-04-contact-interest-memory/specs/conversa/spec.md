# Delta: conversa

## ADDED Requirements

### Requirement: Interesse do cliente alimenta o estágio do contato

O estado de interesse rastreado por turno (`SessionState`) DEVE poder
influenciar o estágio de negócio do contato (`contatos.status`), sem exigir
uma nova heurística de texto independente das já calculadas para intenção e
interesse no mesmo turno.

#### Scenario: Primeiro interesse em produto avança o estágio

- **WHEN** um contato em `novo_lead` menciona pela primeira vez um item do
  catálogo
- **THEN** o estágio do contato avança para `interessado`

#### Scenario: Mensagem neutra não regride o estágio

- **WHEN** um contato já marcado como `interessado` ou `comprando` envia
  uma mensagem sem sinal de interesse ou compra (ex.: saudação)
- **THEN** o estágio do contato permanece o mesmo
