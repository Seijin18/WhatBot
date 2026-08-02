# Design — cliente e parser do Instagram

## Decisão: Instagram API with Instagram Login, não Facebook Login

Alternativas:

1. **Facebook Login para Business**, exigindo Página do Facebook vinculada e
   App Review completo antes de operar com qualquer conta fora da equipe de
   desenvolvimento. Rejeitada: App Review é o maior risco de cronograma do
   projeto (prazo fora do controle do time), e a associação não
   necessariamente tem Página do Facebook ativa.
2. **Instagram API with Instagram Login** (`graph.instagram.com`), disponível
   sob Standard Access sem exigir Página do Facebook vinculada nem App
   Review para contas próprias. Escolhida — é a Decisão 2 de
   `docs/INSTAGRAM_INTEGRATION_PLAN.md`, mantida aqui porque é este change
   que a implementa de fato.

Consequência prática: o host de todas as chamadas é `graph.instagram.com`,
não `graph.facebook.com`; os escopos são `instagram_business_basic` e
`instagram_business_manage_messages` (tarefa 0.3 de `instagram-go-live`,
pré-requisito operacional deste change).

## Decisão: erros tipados espelhando o padrão já usado pelo WhatsApp

`whatsapp_evolution.py` já embrulha falha de transporte em
`ChannelError(retryable=...)` (requisito "Falha de transporte é tipada" em
`openspec/specs/channels/spec.md`). O cliente do Instagram segue o mesmo
padrão, com três causas adicionais específicas do canal: janela de
mensageria expirada, permissão de atendimento humano ausente, rate limit
(com informação de backoff). Não criar uma taxonomia de erro paralela — usar
`ChannelError` com uma causa identificável, para que o tratamento em
`main.py` continue agnóstico de canal.

## Decisão: parser produz `InboundMessage`, não um payload ad-hoc

Segue o requisito já sincronizado em `openspec/specs/channels/spec.md`
("Entrada normalizada em formato único"): o parser do Instagram constrói
`InboundMessage` e deriva o payload de processamento dele, do mesmo jeito que
`webhook.py` já faz para o WhatsApp. Isso é o que permite ao restante do
sistema (identidade, roteamento, fila) não precisar saber a forma bruta do
payload da Meta.

## Casos de borda — por que cada um importa

- **Eco da própria secretaria** respondendo pelo app do Instagram (não pelo
  bot): precisa ser reconhecido e tratado como confirmação de atendimento
  humano, análogo ao que `fromMe` já faz no WhatsApp
  (`test_handover_answers_customer_on_channel_and_admin_on_whatsapp` cobre o
  equivalente de WhatsApp hoje).
- **Menção e resposta a story**: formato de payload diferente de uma DM
  comum; se não tratado, quebra o parser em vez de ser ignorado ou
  processado como texto.
- **Mensagem só com mídia**: sem `text`, o parser não pode assumir que o
  campo existe.
- **Mensagem apagada**: a Meta notifica a deleção; precisa ser distinguida
  de uma mensagem nova para não gerar resposta a um texto vazio.
- **Múltiplos eventos num POST**: o webhook da Meta agrupa eventos; o parser
  precisa iterar, não assumir um evento por requisição.
