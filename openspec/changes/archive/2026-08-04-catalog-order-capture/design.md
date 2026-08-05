# Design — captura de pedidos do catálogo

## Decisão 1: texto sintético em `_extract_text`, não um novo campo em `InboundMessage`

Alternativas consideradas:

1. **Adicionar campo estruturado `order: dict | None` em `InboundMessage`**
   (`whatbot/channels/base.py`). Rejeitada por ora: `InboundMessage` é
   consumido por todo o pipeline (`to_payload()`, `main.py`,
   `channels/instagram.py` também constrói o mesmo dataclass) — mudar o
   schema para um caso que só existe no WhatsApp obrigaria os demais canais
   a lidar com um campo que nunca preenchem. `raw: Dict[str, Any] | None`
   já carrega o payload bruto do webhook; `parse_evolution_payload` (função
   livre, não o dataclass) já retorna um dict solto que `main.py` consome —
   é o lugar certo para anexar `order` sem tocar o contrato do canal.
2. **Texto sintético mínimo em `_extract_text` + `order` anexado pelo
   parser do payload.** Escolhida — mantém `if not text: return None`
   funcionando sem mudança (a mensagem deixa de cair nesse branch porque
   agora sempre tem texto), e não força nenhum outro canal a conhecer o
   conceito de pedido de catálogo.

## Decisão 2: `items_identifiable` como flag derivada, não detecção de plataforma

Cogitou-se inspecionar algum campo do payload que indique Android vs iOS
diretamente. Rejeitada: não há um campo documentado e estável para isso no
payload da Evolution API — o issue #1819 descreve o *efeito* (ausência de
`productId`/`retailerId`), não uma flag de plataforma. Detectar pela
ausência do dado que de fato importa (`items_identifiable = bool(items) and
all(item.get("productId") for item in items)`) é mais robusto: continua
correto mesmo se a causa da falta de identificação mudar no futuro (não é
só um problema de iOS — pode ser qualquer versão futura da Evolution API
que não popule esses campos).

## Decisão 3: handover automático incondicional, complexidade isolada no resumo

Como confirmado com o usuário: todo `orderMessage` real dispara handover
automático, independente de `items_identifiable`. Isso significa que este
change **não precisa** de nenhuma lógica condicional em `priority.py` ou no
disparo do handover — só precisa marcar prioridade 1 e chamar
`executar_handover_para_secretaria` sempre que `order` estiver presente. A
diferença de conteúdo (itens completos vs. "não identificados") é
responsabilidade do `handover-summary-for-agent`, que já vai ter acesso ao
`order` inteiro para decidir o que mostrar — evita duplicar a checagem de
`items_identifiable` em dois lugares do código.
