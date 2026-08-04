# Design — disparo de mensagens em massa via CSV com fila

## Decisão 1: fila persistida no Postgres, não em memória/fila externa

Alternativas consideradas:

1. **Fila em memória dentro de um processo de longa duração.** Rejeitada:
   toda execução do bot neste projeto roda como job Windmill — processo
   novo a cada disparo (`windmill/f/whatbot/handler.py`,
   `check_queue.py`). Qualquer estado em memória se perde entre execuções.
   O mesmo problema já foi resolvido para o streak de falhas de envio
   (`canal_envio_falhas`, `whatbot/instagram_health.py`) trocando memória
   por Postgres — este change segue o mesmo caminho já validado no
   projeto.
2. **Fila gerenciada externa (Redis, RabbitMQ, SQS).** Rejeitada: nenhuma
   dessas peças existe hoje na infra (`docker-compose.yml` só tem
   Postgres, Windmill e a Evolution API) e o volume esperado de disparo em
   massa deste bot não justifica operar mais um serviço — Postgres já é a
   única fonte de estado persistente do projeto, manter assim é
   consistente com o restante do código (`whatbot/db.py` é a única camada
   de persistência).
3. **Tabela dedicada `disparo_mensagens` no Postgres já usado.** Escolhida.

## Decisão 2: três camadas de limite, nenhuma delas nova infraestrutura

O risco central (bloqueio do número por volume/velocidade de envio) é
mitigado por três parâmetros independentes, todos configuráveis por env
var ou pela UI do Windmill, sem precisar de deploy de código para ajustar:

1. **Tamanho do lote por execução** (`CAMPAIGN_BATCH_SIZE`) — limita
   quanto uma única execução do worker processa.
2. **Pausa entre envios dentro do lote**
   (`CAMPAIGN_SEND_INTERVAL_SECONDS`) — evita rajada mesmo dentro de uma
   única execução.
3. **Intervalo do cron do job no Windmill** — limita quantas execuções
   acontecem por hora.

Throughput sustentado = `CAMPAIGN_BATCH_SIZE` execuções/hora. Um
token-bucket ou biblioteca de rate limiting dedicada foi considerada e
rejeitada: as três camadas acima já dão controle suficiente com
ferramentas que o projeto já usa (env vars, cron do Windmill), sem
dependência nova — mesmo espírito de "Python 3.13, sem framework"
(`openspec/project.md`).

## Decisão 3: importação e envio em jobs Windmill separados

Alternativas consideradas:

1. **Um único script que importa e já dispara tudo.** Rejeitada: acopla
   validação/enfileiramento (rápido, síncrono, ideal para feedback
   imediato ao admin sobre linhas inválidas) com envio (deve ser lento e
   espaçado de propósito) — um único script teria que escolher entre
   travar a resposta do import por minutos ou perder o controle de taxa.
2. **Import síncrono (`import_campaign.py`) + worker agendado
   (`send_campaign_queue.py`) separados.** Escolhida — mesmo padrão já
   usado pelo projeto entre `handler.py` (síncrono, responde rápido) e
   `check_queue.py` (agendado, roda em background). O admin importa e já
   recebe o relatório de linhas inválidas na hora; o envio acontece nos
   minutos/horas seguintes, no ritmo configurado.

## Decisão 4: contato com bot pausado não recebe disparo

Um contato com `ia_ativa=FALSE` está, na maior parte dos casos, em
atendimento humano ativo (handover) ou pausado manualmente por um admin
(`admin-bot-pause`). Mandar uma mensagem de campanha por cima disso
conflita com o atendimento em curso. A verificação é feita no momento do
envio (não no momento da importação), porque o estado de `ia_ativa` pode
mudar no intervalo entre importar o CSV e o worker efetivamente processar
aquela linha — checar cedo demais poderia enviar para alguém que foi
pausado depois, ou pular alguém que já foi reativado.
