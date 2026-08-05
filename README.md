# WhatBot — Atendimento Automático via WhatsApp e Instagram

Atendente automático para pequenos negócios: responde clientes pelo
WhatsApp (e opcionalmente Instagram Direct) com IA (Gemini, com fallback
para Ollama local) ancorada numa base de conhecimento editável, transfere
para atendimento humano quando necessário, e deixa a secretaria operar a
fila e outras tarefas por comandos em linguagem natural, tudo pelo próprio
WhatsApp.

Para uma descrição completa da arquitetura, fluxos de dados, módulos,
modelo de dados e variáveis de ambiente, ver
[`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

## Início rápido

1. Copie o exemplo de ambiente e preencha as chaves reais:

```powershell
copy .env.example .env
```

2. Suba o stack:

```powershell
# Windows (PowerShell)
.\run.ps1 up

# ou, com Make instalado (Git Bash / WSL / Linux / macOS)
make up
```

Equivalente direto:

```bash
docker compose --profile windmill up
```

Para rodar em segundo plano: `.\run.ps1 up-d` ou `make up-d` (Windows), ou
`./start-whatbot.sh` (Linux — ver [`WHATBOT-DOCKER-DAEMON.md`](WHATBOT-DOCKER-DAEMON.md)).

3. Configure o Windmill e o webhook da Evolution — passo a passo em
   [`windmill/README.md`](windmill/README.md).

Guia completo de deploy, pareamento do WhatsApp e troubleshooting:
[`DEPLOYMENT.md`](DEPLOYMENT.md).

## Serviços (docker-compose)

| Serviço | Porta | Perfil | Descrição |
|---------|-------|--------|-----------|
| `db` | 5432 | — | Postgres do WhatBot |
| `evolution-db` | — | — | Postgres da Evolution API |
| `redis` | 6379 | — | Cache da Evolution API |
| `evolution-api` | 8080 | — | Integração WhatsApp |
| `windmill-server` | 8000 | `windmill` | UI e API do Windmill |
| `windmill-worker` / `windmill-worker-native` | — | `windmill` | Executam `whatbot.main()` |
| `whatbot` | — | `bot` | Modo alternativo (sem Windmill) |
| `whatbot-ingress` | 8090 | `instagram` | Serviço FastAPI de ingestão do webhook do Instagram |
| `ollama` | 11434 | `ollama` | LLM local opcional (sem custo de API) |

Sem perfis, `docker compose up` sobe apenas a infra (bancos, Redis e
Evolution API). O perfil `windmill` é necessário para o fluxo principal de
produção; `instagram` só é necessário se o canal Instagram estiver
habilitado.

## Funcionalidades

- **Atendimento por IA** ancorado na base de conhecimento (`knowledge/base.md`),
  com fallback em cascata: Gemini → Ollama (se configurado) → resposta
  offline montada da própria base → aviso de indisponibilidade.
- **Handover para humano**: por pedido do cliente, decisão do modelo, ou
  pedido feito pelo catálogo do WhatsApp Business (sempre com prioridade
  máxima, mesmo quando os itens não são identificáveis).
- **Fila de atendimento** com notificações ao admin (imediata, em lote,
  espera prolongada, resumo diário) e comandos em linguagem natural pelo
  WhatsApp: `fila`, `assumir`, `atender`, `atender todos`, `reativar`,
  `pausa o bot para X`, `marca X como cliente ativo`, `marca X como
  empresa/pessoa física`, `status do disparo`, `resumo`, `ajuda`.
- **Modo de simulação** (`#simular` / `#end-simular`): testar o bot como se
  fosse cliente, sem afetar dados reais.
- **Catálogo do WhatsApp Business**: sincronização periódica local
  (`sync_catalog`), resolução de itens de pedido sem chamada de rede
  síncrona.
- **Disparo de mensagens em massa via CSV** (`import_campaign` +
  `send_campaign_queue`): validação linha a linha, taxa configurável,
  retries limitados, pula contatos com bot pausado.
- **Segmentação de contatos**: estágio (`novo_lead → interessado →
  comprando → cliente_ativo`/`cancelado`) e tipo (`b2c`/`b2b`).
- **Instagram Direct (opcional)**: mesmo contrato de canal do WhatsApp,
  janela de mensageria de 24h/7 dias, renovação automática de credencial,
  alertas de saúde da integração. Ver seção 4.2 e 9 de
  [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

## Variáveis de ambiente

Use `.env` na raiz (modelo completo e comentado em
[`.env.example`](.env.example)). Principais variáveis:

| Variável | Descrição |
|----------|-----------|
| `DB_DSN` | Postgres do WhatBot (`postgresql://whatbot:whatbot@db:5432/whatbot`) |
| `EVOLUTION_API_BASE_URL` | URL da Evolution (no compose do bot/worker: `http://evolution-api:8080`) |
| `EVOLUTION_API_KEY` | API key no header `apikey` |
| `EVOLUTION_API_INSTANCE_NAME` | Nome da instância WhatsApp |
| `LLM_PROVIDER` | `gemini` (padrão) ou `ollama` |
| `GEMINI_API_KEY` | Chave Google Gemini (`google-genai`) |
| `GEMINI_MODEL` | Modelo (padrão no código: `gemini-2.5-flash`) |
| `KNOWLEDGE_PATH` | Base de conhecimento (`knowledge/base.md`) |
| `ADMIN_NOTIFY_PHONES` | Números admin para alertas e comandos de fila |
| `TEST_MODE` / `TEST_PHONES` / `TEST_IGSIDS` | Restringe respostas automáticas a uma allowlist por canal |
| `CAMPAIGN_BATCH_SIZE` / `CAMPAIGN_MAX_RETRIES` / `CAMPAIGN_SEND_INTERVAL_SECONDS` | Limites do disparo em massa |
| `IG_APP_ID` / `IG_APP_SECRET` / `IG_WEBHOOK_VERIFY_TOKEN` / ... | Credenciais e config do canal Instagram |

O `docker-compose.yml` não contém segredos reais. Variáveis essenciais em
placeholder fazem o app falhar no startup com erro explícito. Lista completa
em [`.env.example`](.env.example) e detalhada em
[`docs/ARQUITETURA.md`](docs/ARQUITETURA.md#11-variáveis-de-ambiente).

## Comandos úteis

```powershell
.\run.ps1 up-d      # stack em background
.\run.ps1 down      # parar containers
.\run.ps1 logs      # logs principais
.\run.ps1 test      # testes unitários
python scripts/health_check.py
```

## Estrutura do código

Visão detalhada, com o papel de cada módulo, em
[`docs/ARQUITETURA.md`](docs/ARQUITETURA.md#5-módulos-do-pacote-whatbot).
Resumo:

- `whatbot/main.py` — entrypoints Windmill (`main`, `check_queue`,
  `sync_catalog`, `import_campaign`, `send_campaign_queue`)
- `whatbot/config.py` — prompts, timezone e variáveis de ambiente
- `whatbot/knowledge.py` — leitura da base (`knowledge/base.md`)
- `whatbot/tools.py` — ferramentas Gemini (function calling, opcional)
- `whatbot/db.py` — Postgres (contatos, mensagens, fila, catálogo, campanhas)
- `whatbot/channels/` — contrato de canal, roteador, clientes WhatsApp e Instagram
- `whatbot/gemini_client.py` / `ollama_client.py` / `llm.py` — clientes de LLM
- `whatbot/domain.py` — regras de handover e intenções
- `whatbot/webhook.py` / `instagram_webhook.py` — parse de payloads
- `whatbot/queue.py` — fila de atendimento e notificações admin
- `whatbot/admin.py` / `admin_nlu.py` — comandos da secretaria e simulação
- `whatbot/ingress.py` — serviço FastAPI de ingestão do webhook do Instagram
- `windmill/f/whatbot/` — scripts publicados no Windmill
- `scripts/` — pareamento, webhook, health check, OAuth do Instagram

Edite `knowledge/base.md` para produtos/itens, preços, FAQ e contatos.
Formato em [`knowledge/README.md`](knowledge/README.md).

## Desenvolvimento local (sem Docker)

```bash
pip install -r requirements.txt
python -m whatbot.main
```

Se a Evolution API estiver fora do container, ajuste
`EVOLUTION_API_BASE_URL` (no Windows, `http://host.docker.internal:8080`
costuma funcionar para serviços na máquina local).

## Testes

```bash
python -m unittest discover -s tests -p 'test_*.py'
# ou
pytest -q
```

`unittest` puro, sem `conftest.py`/fixtures de pytest; fakes compartilhados
em `tests/fakes.py` (sem rede, sem Postgres real). O teste end-to-end
canônico é `tests/test_main_e2e.py`, entrando por `whatbot.main.main()` — a
mesma porta usada em produção.
