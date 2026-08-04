# Design — resumo de interesse/estágio na notificação de handover

## Decisão 1: resumo determinístico, não gerado por LLM

Cogitou-se pedir à LLM um resumo em linguagem natural do histórico. Rejeitada:
`history_summary()` já resolve o mesmo problema (resumo curto de tópicos
recentes) de forma determinística, sem custo de chamada de rede/latência
extra bem no momento em que o handover precisa ser notificado o mais rápido
possível. Este change estende o mesmo padrão (concatenar sinais conhecidos
em uma frase curta), não substitui por geração de texto.

## Decisão 2: degradação graciosa sem `catalog-product-sync`

`build_contact_summary` não deve falhar nem ficar vazio se
`catalog-product-sync` ainda não existir ou o cache estiver vazio para um
`productId` específico — nesse caso, a seção de pedido do resumo cai para o
que `catalog-order-capture` já capturou bruto (`order_title`/`item_count`),
sem nome resolvido. Isso mantém os dois changes de catálogo
verdadeiramente não-bloqueantes um do outro, como já registrado nas duas
propostas.

## Decisão 3: reaproveitar `format_waiting_list`, não duplicar formatação

`format_waiting_list` já é o único lugar que monta a lista de contatos
aguardando para o admin. Trocar o preview de 120 caracteres por
`build_contact_summary` ali, em vez de criar uma segunda função de
formatação para o comando "quem está na fila?", evita que as duas
superfícies (notificação imediata e listagem sob demanda) divirjam no que
mostram.
