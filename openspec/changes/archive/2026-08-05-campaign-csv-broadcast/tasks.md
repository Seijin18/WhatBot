# Tasks — disparo de mensagens em massa via CSV com fila

## 1. Schema

- [x] 1.1 Tabela `disparo_mensagens` em `ensure_schema()` (`whatbot/db.py`),
      colunas conforme `proposal.md`, criação idempotente
      (`CREATE TABLE IF NOT EXISTS`)
- [x] 1.2 Índice em `(lote, status)` para as consultas de status por lote e
      de seleção de pendentes (`CREATE INDEX IF NOT EXISTS`)

## 2. Importação de CSV

- [x] 2.1 `whatbot.main.import_campaign(csv_content: str, lote: str) ->
      dict`: parseia com `csv.DictReader`, exige colunas `telefone` e
      `mensagem`; `tipo_cliente` é opcional (→ Requirement "Importação
      valida linha a linha sem falhar o lote inteiro")
- [x] 2.2 Telefone inválido (não normalizável por `normalize_phone`) ou
      mensagem vazia: linha reportada em `dict["erros"]` com o número da
      linha e o motivo, sem interromper o processamento das demais
- [x] 2.3 Linhas válidas inseridas em `disparo_mensagens` com
      `status='pendente'`
- [x] 2.4 Coluna opcional `tipo_cliente`: se presente e válida
      (`"b2c"`/`"b2b"`), tenta `Database.set_contact_tipo_cliente` no
      contato correspondente ao telefone, se ele já existir — best-effort,
      não falha a linha se o contato ainda não existir
- [x] 2.5 `windmill/f/whatbot/import_campaign.py`: script fino delegando
      para `whatbot.main.import_campaign`, mesmo padrão de bootstrap de
      `.env`/`sys.path` de `windmill/f/whatbot/handler.py`

## 3. Worker de envio

- [x] 3.1 `whatbot.main.send_campaign_queue() -> dict`: seleciona até
      `CAMPAIGN_BATCH_SIZE` (env var, default `20`) linhas `pendente` mais
      antigas (`ORDER BY criado_em`)
- [x] 3.2 Para cada linha: se o contato correspondente tem `ia_ativa =
      FALSE`, marca `status='pulado'` e não envia (→ Requirement "Contato
      com bot pausado não recebe disparo em massa")
- [x] 3.3 Envio via `whatbot/channels/router.py::send_to_contact`; sucesso
      marca `enviado` + `enviado_em`
- [x] 3.4 `ChannelError(retryable=True)`: se `tentativas + 1 <
      CAMPAIGN_MAX_RETRIES` (env var, default `3`), incrementa
      `tentativas` e mantém `pendente`; senão marca `falha` com o erro
- [x] 3.5 `ChannelError(retryable=False)`: marca `falha` direto, sem
      consumir tentativa extra
- [x] 3.6 `time.sleep(CAMPAIGN_SEND_INTERVAL_SECONDS)` (env var, default
      `3`) entre cada envio do batch — não dormir depois do último item
- [x] 3.7 `windmill/f/whatbot/send_campaign_queue.py`: script fino
      delegando para `whatbot.main.send_campaign_queue`, mesmo padrão de
      `windmill/f/whatbot/check_queue.py`
- [x] 3.8 Documentar no README/DEPLOYMENT (ou neste `tasks.md`, seção
      operacional) que o cron deste job precisa ser configurado
      manualmente na UI do Windmill, sugestão inicial de intervalo (ex.: a
      cada 2 minutos)

### Nota operacional (3.8)

Depois do deploy deste change, um operador precisa, na UI do Windmill:

1. Publicar `f/whatbot/send_campaign_queue` como script.
2. Criar um *schedule* (cron) apontando para ele — sugestão inicial:
   a cada 2 minutos (`*/2 * * * *`). Ajustar a cadência junto com
   `CAMPAIGN_BATCH_SIZE`/`CAMPAIGN_SEND_INTERVAL_SECONDS` para o throughput
   desejado (design.md, Decisão 2: throughput sustentado =
   `CAMPAIGN_BATCH_SIZE` × execuções por hora).
3. `f/whatbot/import_campaign` fica sem schedule — é disparado manualmente
   pelo admin, passando `csv_content` (conteúdo do arquivo) e `lote`
   (rótulo do lote) como parâmetros, mesmo modelo operacional de
   `refresh_ig_token.py`.

Não há endpoint HTTP novo nem UI de upload — a importação acontece pela
tela de execução manual de script da própria UI do Windmill.

## 4. Comando de status para o admin

- [x] 4.1 Nova intenção `campaign_status` em `whatbot/admin_nlu.py` (ex.:
      "como está o disparo <lote>", "quantos faltam no <lote>")
- [x] 4.2 `Database.get_campaign_status(lote: str) -> dict`: contagem por
      `status` para o lote informado
- [x] 4.3 Resposta ao admin com a contagem (pendente/enviado/falha/pulado)

## 5. Testes

- [x] 5.1 Importação: CSV válido enfileira todas as linhas como
      `pendente`; CSV com uma linha de telefone inválido enfileira as
      demais e reporta a linha ruim sem derrubar o import
- [x] 5.2 Importação com coluna `tipo_cliente` atualiza o contato existente
      correspondente; não falha quando o contato não existe ainda
- [x] 5.3 Worker respeita `CAMPAIGN_BATCH_SIZE`: fila com mais linhas que o
      batch só processa o limite numa execução
- [x] 5.4 Worker pula (`pulado`) contato com `ia_ativa=False` sem chamar
      `send_to_contact`
- [x] 5.5 Falha retryable dentro do limite de tentativas mantém
      `pendente` e incrementa `tentativas`; falha retryable esgotada vira
      `falha`; falha não-retryable vira `falha` direto
- [x] 5.6 Worker dorme `CAMPAIGN_SEND_INTERVAL_SECONDS` entre envios
      (mockar `time.sleep` e contar chamadas)
- [x] 5.7 Comando de status retorna contagem correta por lote
- [x] 5.8 Suíte completa verde (`make test` / `pytest -q`)
