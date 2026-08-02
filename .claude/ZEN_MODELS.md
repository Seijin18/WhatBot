# Zen — guia de modelos por aplicação (custo x eficiência)

Fonte de verdade única para qual modelo da OpenRouter usar em cada chamada de
`zen chat` / `zen consensus` / `zen challenge` / `zen planner` disparada pelos
subagentes (`planner`, `critic`, `scope-explorer`) e comandos (`/ideate`,
`/develop`). Preços em USD por milhão de tokens, levantados via
`https://openrouter.ai/api/v1/models` — reconfirme periodicamente, catálogo e
preços da OpenRouter mudam com frequência.

## Regra adaptável (sempre aplicar)

1. Tente primeiro o **modelo pago recomendado** da tabela abaixo para a
   aplicação em questão.
2. Se a chamada falhar com erro `402` / "insufficient credits" / "This
   request requires more credits" — **não pare nem pergunte ao usuário**:
   refaça a mesma chamada trocando só o `model` pelo **modelo free** da
   mesma linha, e prossiga normalmente.
3. Ao reportar o resultado, mencione en passant que caiu para o tier free
   por falta de crédito (uma frase, não precisa alarde) — assim o usuário
   sabe que pode adicionar crédito se quiser a qualidade do tier pago de
   volta.
4. Se o usuário nomear um modelo explicitamente na conversa (ex: "usa
   consensus com opus e o3-pro"), use exatamente esse modelo — essa regra
   de fallback só vale para as escolhas automáticas dos agentes, nunca
   sobrepõe um pedido explícito do usuário.

## Tabela por aplicação

| Aplicação | Modelo pago recomendado | Preço (in/out por M) | Fallback free |
|---|---|---|---|
| `scope-explorer` → `consensus`, postura "viabilidade técnica" | `google/gemini-2.5-flash` | $0.30 / $2.50 | `openai/gpt-oss-20b:free` |
| `scope-explorer` → `consensus`, postura "valor pro usuário" | `deepseek/deepseek-r1-0528` | $0.50 / $2.15 | `openai/gpt-oss-20b:free` |
| `critic` → `challenge` (checagem padrão de viés de concordância) | `moonshotai/kimi-k2.5` | $0.57 / $2.85 | `openai/gpt-oss-20b:free` |
| `critic` → `consensus`, postura "a favor" | `google/gemini-2.5-pro` | $1.25 / $10.00 | `openai/gpt-oss-20b:free` |
| `critic` → `consensus`, postura "contra" | `deepseek/deepseek-r1-0528` | $0.50 / $2.15 | `openai/gpt-oss-20b:free` |
| `planner` → `zen planner` (segunda passada) | `google/gemini-2.5-pro` | $1.25 / $10.00 | `openai/gpt-oss-20b:free` |
| Chat genérico / dúvida pontual | `moonshotai/kimi-k2.5` | $0.57 / $2.85 | `openai/gpt-oss-20b:free` |

Custo típico de uma chamada nesses modelos pagos (poucos milhares de tokens
de contexto + resposta): frações de centavo. Com $5 de crédito dá pra rodar
centenas de `consensus`/`challenge` antes de precisar recarregar.

## Faixa premium — só sob pedido explícito

Nunca escolha estes automaticamente; use apenas se o usuário pedir "máximo
rigor" ou nomear o modelo diretamente. São 15-40x mais caros que a faixa
recomendada acima, sem ganho proporcional pro caso de uso típico de
consensus/challenge:

| Modelo | Preço (in/out por M) |
|---|---|
| `anthropic/claude-opus-4.5` | $5.00 / $25.00 |
| `openai/gpt-5.2` | $1.75 / $14.00 |
| `openai/o3-pro` | $20.00 / $80.00 |
| `openai/gpt-5.2-pro` | $21.00 / $168.00 |

Nota: os subagentes `planner` e `critic` já rodam nativamente em
`model: opus` (frontmatter do próprio subagente, cota do plano Claude Pro,
sem custo de OpenRouter) — não há motivo para pagar Opus de novo via Zen. O
Zen serve para pegar a opinião de um modelo de **outra família** (Gemini,
GPT, DeepSeek, Kimi), que é o que dá valor real ao `consensus`/`challenge`.

## Catálogo `:free` atual (zero custo, mudam com frequência)

Confirmado funcionando em teste real: `openai/gpt-oss-20b:free`. Outros
disponíveis no momento desta pesquisa — confira
`https://openrouter.ai/models?max_price=0` para a lista atual antes de
assumir que um destes ainda existe:

`google/gemma-4-31b-it:free`, `nvidia/nemotron-3-nano-30b-a3b:free`,
`nvidia/nemotron-3-super-120b-a12b:free`, `inclusionai/ling-3.0-flash:free`,
`cohere/north-mini-code:free`, `openrouter/free`.
