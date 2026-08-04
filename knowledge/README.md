# Base de conhecimento do negócio

Edite o arquivo **`base.md`** para atualizar as informações que o agente de vendas e o assistente usam nas respostas.

Não é necessário reiniciar containers: o WhatBot recarrega o arquivo automaticamente quando ele é salvo.

## Estrutura do arquivo

```markdown
# Nome do negócio

## Sobre
Texto livre...

## Endereço e contato
- Endereço: ...
- Telefone: ...

## Itens

### Nome do produto/serviço/item
- Horários: ...
- Preço mensal: ...
- Público-alvo: ...
- Observações: ...

## Como comprar e pagamento
Texto ou lista com taxas, formas de pagamento, documentos...

## FAQ

### Pergunta frequente?
Resposta...
```

A seção `## Itens` é opcional — negócios sem agenda de aulas/turmas
(ex.: catálogo de produtos sob encomenda) simplesmente não a incluem; o bot
usa a tabela de `## Preços` como referência principal nesse caso.

## Campos reconhecidos nos itens

Use estes rótulos (com dois-pontos) para que as ferramentas encontrem os dados:

- **Horários**
- **Preço mensal**
- **Público-alvo**
- **Observações**

## Ferramentas do agente (automáticas)

O Gemini consulta estas funções antes de responder:

| Ferramenta | Uso |
|------------|-----|
| `listar_itens` | Lista todos os produtos/serviços/itens |
| `buscar_horarios_turmas` | Horários de um item |
| `buscar_precos` | Preços e regras de compra/pagamento |
| `buscar_info_negocio` | Endereço, contato, sobre, etc. |
| `buscar_faq` | Perguntas frequentes |

## Caminho customizado

No `.env`:

```
KNOWLEDGE_PATH=/caminho/para/seu/arquivo.md
```

No Docker/Windmill o padrão é `/whatbot/knowledge/base.md`.
