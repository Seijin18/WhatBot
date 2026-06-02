# Base de conhecimento da associação

Edite o arquivo **`associacao.md`** para atualizar as informações que o agente de vendas e o assistente usam nas respostas.

Não é necessário reiniciar containers: o WhatBot recarrega o arquivo automaticamente quando ele é salvo.

## Estrutura do arquivo

```markdown
# Nome da associação

## Sobre a associação
Texto livre...

## Endereço e contato
- Endereço: ...
- Telefone: ...

## Modalidades

### Nome da modalidade
- Horários: ...
- Preço mensal: ...
- Público-alvo: ...
- Observações: ...

## Matrícula e pagamentos
Texto ou lista com taxas, formas de pagamento, documentos...

## FAQ

### Pergunta frequente?
Resposta...
```

## Campos reconhecidos nas modalidades

Use estes rótulos (com dois-pontos) para que as ferramentas encontrem os dados:

- **Horários**
- **Preço mensal**
- **Público-alvo**
- **Observações**

## Ferramentas do agente (automáticas)

O Gemini consulta estas funções antes de responder:

| Ferramenta | Uso |
|------------|-----|
| `listar_modalidades` | Lista todas as atividades |
| `buscar_horarios_turmas` | Horários de uma modalidade |
| `buscar_precos` | Preços e regras de matrícula |
| `buscar_info_associacao` | Endereço, contato, sobre, etc. |
| `buscar_faq` | Perguntas frequentes |

## Caminho customizado

No `.env`:

```
ASSOCIACAO_KNOWLEDGE_PATH=/caminho/para/seu/arquivo.md
```

No Docker/Windmill o padrão é `/whatbot/knowledge/associacao.md`.
