# Design — contato tem tipo de cliente B2C/B2B

## Decisão 1: coluna simples com default, sem tabela separada

Alternativas consideradas:

1. **Tabela separada `clientes_b2b` com FK para `contatos`.** Rejeitada:
   não há hoje nenhum atributo adicional específico de B2B (razão social,
   CNPJ, contato responsável) que justifique uma tabela própria — seria
   normalização especulativa para um dado que hoje é só um rótulo. Se
   esses atributos aparecerem no futuro, migrar para tabela própria é uma
   migração aditiva simples, não uma reescrita.
2. **Enum no Postgres (`CREATE TYPE tipo_cliente_enum AS ENUM (...)`).**
   Rejeitada: nenhuma outra coluna deste projeto usa enum de banco
   (`status` e `canal` são `VARCHAR` livres, validados em Python) —
   introduzir um padrão novo só para este campo quebra a consistência do
   arquivo sem ganho real, e enums do Postgres são mais caros de alterar
   depois (exigem `ALTER TYPE`) do que trocar uma validação em Python.
3. **`VARCHAR(8) NOT NULL DEFAULT 'b2c'`, validado em Python.** Escolhida —
   mesmo padrão de `status`/`canal` já usados neste arquivo.

## Decisão 2: default `b2c`, não `NULL`

Contatos existentes e novos contatos criados pelo fluxo normal (webhook de
cliente) são, na esmagadora maioria, pessoas físicas — `b2c` como default
evita que todo consumidor futuro do campo (ex.: filtro de campanha) precise
tratar um terceiro estado "desconhecido". Quem precisa da distinção B2B
marca explicitamente via comando do admin.

## Decisão 3: comando de admin, não inferência automática

Cogitou-se inferir B2B a partir de heurísticas (nome com "Ltda"/"ME", texto
da conversa mencionando CNPJ). Rejeitada nesta fase: heurística de texto é
frágil, e o volume de contatos que precisam dessa marcação é pequeno o
suficiente para a secretaria marcar manualmente — mesma lógica já aplicada
a outras decisões operacionais deste bot (assumir/completar/reativar são
todos comandos manuais do admin, não automáticos).
