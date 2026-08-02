# Design — serviço de ingestão do webhook do Instagram

## Decisão: serviço FastAPI dedicado, não apontar o webhook direto para o Windmill

Alternativas:

1. **Apontar o webhook da Meta direto para `windmill/f/whatbot/handler.py`**,
   como já acontece para o WhatsApp (que não tem o requisito de ACK <20s da
   Meta com a mesma rigidez, e cuja Evolution API já absorve parte da
   confirmação). Rejeitada para o Instagram: o handler do Windmill roda
   `main()` de ponta a ponta, incluindo a chamada ao LLM, antes de devolver
   resposta HTTP. Sob latência ruim do modelo, isso estoura os 20s e a Meta
   reentrega — sem idempotência, duplica a resposta ao cliente.
2. **Serviço HTTP dedicado** (`whatbot/ingress.py`, FastAPI) que só faz:
   handshake de verificação, validação de assinatura, confirmação imediata,
   e enfileira o processamento real (que ainda termina chamando
   `whatbot.main.main(payload)`, preservando o caminho de domínio existente)
   fora do ciclo de resposta. Escolhida — é a Decisão 4 completa de
   `docs/INSTAGRAM_INTEGRATION_PLAN.md`.

O processamento de fato continua reaproveitando `whatbot.main.main()` — este
change não duplica a lógica de negócio, só desacopla a confirmação HTTP da
execução.

## Decisão: idempotência por `message_id`, checada antes do processamento

`webhook_eventos` (schema criado em `identity-multichannel`) registra o
`message_id` de todo evento aceito. Antes de processar, o serviço checa se o
`message_id` já foi visto; se sim, descarta sem erro (a Meta trata "sem
erro" como sucesso e para de reentregar). A limpeza periódica dessa tabela
já está prevista no job agendado existente do Windmill.

## Decisão: validação de assinatura em tempo constante, sobre o corpo bruto

Comparação ingênua de string (`==`) vaza timing e permite ataque de
temporização sobre o segredo do webhook. A validação usa comparação em tempo
constante (`hmac.compare_digest` ou equivalente) sobre os bytes brutos do
corpo da requisição — não sobre o corpo já desserializado, porque
reserialização pode alterar bytes (ordem de chaves, espaçamento) e invalidar
uma assinatura originalmente válida.

## Não-objetivos

- Fila de mensagens persistente entre o webhook e o processamento (ex.:
  Redis/Celery) — o volume esperado não justifica a complexidade agora;
  "processar fora do ciclo de resposta" pode ser resolvido com uma tarefa em
  background do próprio processo FastAPI. Se o volume crescer, revisitar.
