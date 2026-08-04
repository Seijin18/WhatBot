# Design — sincronização local do catálogo

## Decisão 1: tabela própria `produtos_catalogo`, não JSONB genérico

Alternativas consideradas:

1. **Cachear o catálogo inteiro como um blob JSON numa única linha de
   config.** Rejeitada: resolver `productId → nome/preço` a partir de um
   blob exige desserializar e varrer a lista inteira a cada resolução; uma
   tabela indexada por `product_id` resolve em O(1) por item e permite
   `resolve_catalog_items` com um único `SELECT ... WHERE product_id =
   ANY(%s)`, que é exatamente o padrão de acesso que `catalog-order-capture`
   e `handover-summary-for-agent` precisam (resolver N ids de uma vez).
2. **Tabela própria com upsert por `product_id`.** Escolhida — mesmo
   critério já usado em `contact-segmentation-b2b-b2c/design.md` Decisão 1:
   só criar estrutura nova quando o dado justifica, e aqui justifica (é uma
   entidade de negócio própria — produto —, não um atributo de outra
   entidade).

## Decisão 2: sincronização periódica com upsert, não fetch sob demanda

Cogitou-se chamar `fetch_catalog()` a cada resolução (sem cache). Rejeitada:
adicionaria uma chamada HTTP síncrona à Evolution API no meio do
processamento de toda mensagem que menciona produto, e no meio do fluxo de
handover de um pedido — risco de latência e de falha de rede bloqueando o
atendimento. Sincronização periódica (mesmo padrão de job agendado que já
existe em `windmill/f/whatbot/check_queue.py`) mantém `produtos_catalogo`
como cache local, e a resolução em tempo real vira uma consulta Postgres
simples, já otimizada e sem dependência de rede externa no caminho crítico.

## Decisão 3: Graph API oficial documentada como melhoria futura, não avaliada agora

Ver "Fora de escopo" em `proposal.md`. Registrado aqui só para deixar
explícito o critério de quando reconsiderar: se a operação relatar
problemas recorrentes de estabilidade com a Evolution API (desconexões,
necessidade de reparear QR code) que justifiquem migrar toda a integração
de canal — nesse momento a decisão de catálogo seria reavaliada junto,
não isoladamente.
