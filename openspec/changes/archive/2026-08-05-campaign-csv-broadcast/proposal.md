# Disparo de mensagens em massa via CSV, com fila e limite de taxa

## Why

Hoje não existe nenhum jeito de disparar uma série de mensagens
direcionadas (contato + mensagem específica por contato) a partir de uma
lista — só o envio individual já coberto pelo fluxo de conversa. Fazer
isso hoje exigiria um script manual chamando `EvolutionApiClient.send_text`
direto, sem fila nem limite de taxa nenhum
(`whatbot/channels/whatsapp_evolution.py` não implementa nenhum rate
limiting — só timeout de 10s e retry em erro de transporte). Enviar um
lote grande em rajada por uma instância Baileys/Evolution API é um risco
real de bloqueio do número.

## What Changes

- Nova tabela `disparo_mensagens` em `ensure_schema()` (`whatbot/db.py`),
  mesmo padrão idempotente das demais tabelas:
  - `id SERIAL PRIMARY KEY`
  - `lote VARCHAR(128) NOT NULL` — rótulo do lote/arquivo importado, para
    agrupar e consultar status
  - `canal VARCHAR(32) NOT NULL DEFAULT 'whatsapp'`
  - `external_id VARCHAR(64) NOT NULL` — telefone (ou identificador do
    canal)
  - `mensagem TEXT NOT NULL`
  - `status VARCHAR(16) NOT NULL DEFAULT 'pendente'` —
    `pendente`/`enviado`/`falha`/`pulado`
  - `tentativas INTEGER NOT NULL DEFAULT 0`
  - `erro TEXT`
  - `criado_em TIMESTAMP WITH TIME ZONE DEFAULT now()`
  - `enviado_em TIMESTAMP WITH TIME ZONE`
- Novo script Windmill de importação,
  `windmill/f/whatbot/import_campaign.py` (disparo manual do admin pela UI
  do Windmill — não um endpoint HTTP novo, mesmo modelo operacional de
  `refresh_ig_token.py`), delegando para
  `whatbot.main.import_campaign(csv_content: str, lote: str) -> dict`:
  - Parseia com o módulo `csv` da biblioteca padrão (sem dependência nova)
  - Colunas esperadas: `telefone`, `mensagem`, e opcionalmente
    `tipo_cliente`
  - Reaproveita `normalize_phone` (`whatbot/queue.py`) para validar/normalizar
    telefone
  - Linha inválida (telefone não normalizável, mensagem vazia) é reportada
    no retorno sem falhar o lote inteiro
  - Se a coluna `tipo_cliente` vier preenchida, tenta usar
    `Database.set_contact_tipo_cliente` no contato correspondente (se
    existir) — acoplamento leve e opcional com o change
    `contact-segmentation-b2b-b2c`; se aquele change não estiver
    implementado ainda, esta coluna é simplesmente ignorada
- Novo job agendado, `windmill/f/whatbot/send_campaign_queue.py` (mesmo
  padrão fino de `windmill/f/whatbot/check_queue.py`), delegando para
  `whatbot.main.send_campaign_queue() -> dict`:
  - Puxa até `CAMPAIGN_BATCH_SIZE` (env var, default `20`) linhas
    `pendente`, mais antigas primeiro
  - Contato com `ia_ativa = FALSE` no momento do envio é marcado `pulado`
    (não interfere em atendimento humano em andamento)
  - Envia via `whatbot/channels/router.py::send_to_contact` — nunca client
    concreto direto, respeitando a única fronteira de saída do projeto
    (`openspec/project.md`, "Camadas")
  - Sucesso → `enviado`, `enviado_em = now()`
  - `ChannelError(retryable=True)` com `tentativas < CAMPAIGN_MAX_RETRIES`
    (env var, default `3`) → incrementa `tentativas`, mantém `pendente`
    para o próximo run
  - `ChannelError(retryable=False)` ou `tentativas` esgotadas → `falha`,
    erro salvo em `erro`
  - `time.sleep(CAMPAIGN_SEND_INTERVAL_SECONDS)` (env var, default `3`)
    entre envios do mesmo lote — pacing dentro do run
  - A cadência do próprio cron do Windmill (configurada manualmente na UI,
    documentada em `tasks.md`) é a terceira camada de limite — throughput
    sustentado = `CAMPAIGN_BATCH_SIZE` × execuções por hora, ajustável só
    mudando env var + intervalo do cron, sem deploy de código
- Novo comando de admin para consultar status de um lote ("como está o
  disparo <lote>", "quantos faltam no <lote>") — contagem por `status`
  agrupada por `lote`, nova intenção em `whatbot/admin_nlu.py`

## Impact

- Specs afetadas: `campaigns` (capability nova)
- Código alterado: `whatbot/db.py`, `whatbot/main.py`,
  `whatbot/admin_nlu.py`, `whatbot/admin.py`, novos
  `windmill/f/whatbot/import_campaign.py` e
  `windmill/f/whatbot/send_campaign_queue.py`
- Testes alterados: novo `tests/test_campaign.py`; `tests/fakes.py` ganha
  os fakes necessários para a nova tabela
- Bloqueado por: nenhum
- Acoplamento leve e não bloqueante com `contact-segmentation-b2b-b2c`
  (coluna opcional `tipo_cliente` no CSV) — ver "What Changes"
- Operacional (fora do código, registrado em `tasks.md`): configurar o
  cron do novo job `send_campaign_queue` na UI do Windmill, mesma operação
  manual já feita hoje para `check_queue.py`

## Fora de escopo (decisão explícita)

- Editor de mensagem por template com variáveis (`{{nome}}`) — o CSV traz
  a mensagem final já pronta por linha; suporte a template é uma melhoria
  aditiva futura, não bloqueia o valor deste change
- Envio por Instagram — a integração de Instagram ainda não está em
  produção (`openspec/changes/instagram-go-live` não implementado);
  `canal` já é um campo da tabela para não exigir migração quando isso
  mudar, mas o worker desta versão assume WhatsApp
- Interface web de upload de CSV — a importação é via script Windmill
  (parâmetro de texto), consistente com o resto da operação deste bot, que
  não tem frontend próprio
