# Delta: identity

## MODIFIED Requirements

### Requirement: Filtro de teste por canal

`should_respond_to_customer` DEVE decidir por `(canal, external_id)`. Cada
canal tem sua própria variável de lista de teste (`TEST_PHONES` para
WhatsApp, `TEST_IGSIDS` para Instagram, seguindo a mesma convenção de nome
para canais futuros).

Em `TEST_MODE`, um canal sem lista de teste configurada DEVE bloquear por
padrão (fail-closed) — nunca responder por engano a um público não
pretendido só porque a lista daquele canal está vazia ou ausente.

Para o Instagram especificamente, o canário de lançamento usa esse mesmo
mecanismo: `TEST_IGSIDS` populado restringe a resposta automática às contas
de teste antes da abertura geral.

#### Scenario: TEST_MODE com lista própria configurada

- **WHEN** `TEST_MODE` está ativo e um contato de um canal com lista
  configurada envia mensagem
- **THEN** a resposta é enviada se e somente se a identidade externa do
  contato está na lista daquele canal

#### Scenario: TEST_MODE sem lista configurada para o canal

- **WHEN** `TEST_MODE` está ativo e um canal não tem variável de lista de
  teste configurada
- **THEN** nenhum contato daquele canal recebe resposta automática
  (fail-closed)

#### Scenario: Lista de um canal não vaza para outro

- **WHEN** a identidade externa de um contato de um canal coincide,
  textualmente, com uma entrada da lista de teste de outro canal
- **THEN** a comparação é feita só dentro do mesmo canal — a entrada da
  lista de outro canal não autoriza nem bloqueia esse contato

#### Scenario: Contato fora da lista durante o canário do Instagram

- **WHEN** um contato do Instagram fora de `TEST_IGSIDS` manda mensagem com
  o canário ativo
- **THEN** nenhuma resposta automática é enviada (instância do cenário
  "TEST_MODE sem lista configurada para o canal" / "com lista própria
  configurada", aplicada ao Instagram)

#### Scenario: Contato da lista de teste recebe resposta normal

- **WHEN** um contato do Instagram em `TEST_IGSIDS` manda mensagem com o
  canário ativo
- **THEN** o ciclo completo (identidade, conhecimento, resposta) funciona
  normalmente
