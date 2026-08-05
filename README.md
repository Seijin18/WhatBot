# WhatBot — Atendimento Automático via WhatsApp

Serviço de atendimento via WhatsApp com IA (Gemini), Evolution API e orquestração no Windmill (self-hosted Docker).

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

Para rodar em segundo plano: `.\run.ps1 up-d` ou `make up-d`.

3. Configure o Windmill e o webhook da Evolution — passo a passo em [`windmill/README.md`](windmill/README.md).

Guia completo de deploy, pareamento do WhatsApp e troubleshooting: [`DEPLOYMENT.md`](DEPLOYMENT.md).

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

Sem perfis, `docker compose up` sobe apenas a infra (bancos, Redis e Evolution API). O perfil `windmill` é necessário para o fluxo principal de produção.

## Variáveis de ambiente

Use `.env` na raiz (modelo em [`.env.example`](.env.example)). Principais variáveis:

| Variável | Descrição |
|----------|-----------|
| `DB_DSN` | Postgres do WhatBot (`postgresql://whatbot:whatbot@db:5432/whatbot`) |
| `EVOLUTION_API_BASE_URL` | URL da Evolution (no compose do bot/worker: `http://evolution-api:8080`) |
| `EVOLUTION_API_KEY` | API key no header `apikey` |
| `EVOLUTION_API_INSTANCE_NAME` | Nome da instância WhatsApp |
| `GEMINI_API_KEY` | Chave Google Gemini (`google-genai`) |
| `GEMINI_MODEL` | Modelo (padrão no código: `gemini-2.5-flash`) |
| `ADMIN_NOTIFY_PHONES` | Números admin para alertas e comandos de fila |
| `KNOWLEDGE_PATH` | Base de conhecimento (`knowledge/base.md`) |

O `docker-compose.yml` não contém segredos reais. Variáveis essenciais em placeholder fazem o app falhar no startup com erro explícito.

## Comandos úteis

```powershell
.\run.ps1 up-d      # stack em background
.\run.ps1 down      # parar containers
.\run.ps1 logs      # logs principais
.\run.ps1 test      # testes unitários
python scripts/health_check.py
```

## Estrutura do código

- `whatbot/main.py` — entrypoint Windmill `main(payload: dict)`
- `whatbot/config.py` — prompts, timezone e variáveis de ambiente
- `whatbot/knowledge.py` — leitura da base (`knowledge/base.md`)
- `whatbot/tools.py` — ferramentas Gemini (function calling)
- `whatbot/db.py` — Postgres (contatos, mensagens, fila)
- `whatbot/whatsapp.py` — cliente Evolution API
- `whatbot/gemini_client.py` — wrapper Gemini com tools e fallback de modelo
- `whatbot/domain.py` — regras de handover e intenções
- `whatbot/webhook.py` — parse de payloads da Evolution
- `whatbot/queue.py` — fila de atendimento e notificações admin
- `whatbot/admin.py` / `whatbot/admin_nlu.py` — comandos da secretaria
- `windmill/f/whatbot/` — scripts publicados no Windmill
- `scripts/` — pareamento, webhook, health check

Edite `knowledge/base.md` para produtos/itens, preços, FAQ e contatos. Formato em [`knowledge/README.md`](knowledge/README.md).

## Desenvolvimento local (sem Docker)

```bash
pip install -r requirements.txt
python -m whatbot.main
```

Se a Evolution API estiver fora do container, ajuste `EVOLUTION_API_BASE_URL` (no Windows, `http://host.docker.internal:8080` costuma funcionar para serviços na máquina local).
