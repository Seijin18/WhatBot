# Windmill setup for WhatBot

## 1. Subir Windmill

```powershell
cd C:\Projetos\WhatBot
docker compose --profile windmill up -d
```

Acesse: http://localhost:8000

Login inicial (primeira vez):
- Email: `admin@windmill.dev`
- Senha: `changeme`

## 2. Criar o script no Windmill

1. Abra **Scripts** → **+ New script** → **Python**
2. Nome/caminho: `whatbot/handler`
3. Cole o conteudo de `windmill/f/whatbot/handler.py`
4. Salve e deploy

Ou importe via CLI (se tiver `wmill` instalado):

```powershell
pip install wmill
cd windmill
wmill sync push
```

## 3. Habilitar webhook no script

1. Abra o script `whatbot/handler`
2. Aba **Triggers** → **Webhooks** → habilite o webhook
3. Copie a URL exibida

**Duas URLs, dois contextos:**

| Onde usar | Host na URL | Exemplo |
|-----------|-------------|---------|
| Navegador / teste manual | `localhost` | `http://localhost:8000/api/w/admins/...` |
| Evolution API (dentro do Docker) | `windmill-server` | `http://windmill-server:8000/api/w/admins/...` |

> `windmill-server` **nao abre no navegador** — e so um nome interno da rede Docker.

## 4. Registrar webhook na Evolution API

```powershell
python scripts/register_windmill_webhook.py
```

O script usa `localhost:8080` para falar com a Evolution (no host) e registra
`windmill-server:8000` como destino do webhook (rede Docker).

Ou manualmente:

```powershell
python scripts/setup_webhook.py "http://windmill-server:8000/api/w/admins/webhooks/webhook/f/whatbot/handler"
```

Com token Windmill (se criou um na aba Triggers):

```powershell
python scripts/setup_webhook.py "http://windmill-server:8000/api/w/admins/jobs/run/p/f/whatbot/handler" --auth-header "Bearer SEU_TOKEN"
```

## 5. Variaveis de ambiente no Windmill

O worker native ja recebe as variaveis do `.env` via docker-compose.
Confirme em **Settings → Workers** que o worker `native` esta ativo.

Variaveis necessarias:
- `GEMINI_API_KEY`
- `DB_DSN=postgresql://whatbot:whatbot@db:5432/whatbot`
- `EVOLUTION_API_KEY`
- `EVOLUTION_API_INSTANCE_NAME`
- `EVOLUTION_API_BASE_URL=http://evolution-api:8080`
- `GEMINI_MODEL=gemini-2.0-flash-lite`

## 6. Testar

Envie uma mensagem para o WhatsApp Business pareado.
Verifique logs:

```powershell
docker logs windmill_worker -f
docker logs evolution_api -f --tail 30
```

## 7. Fila de atendimento e alertas admin

Configure no `.env`:

```env
# Vários números separados por vírgula — todos recebem alertas e podem usar comandos
ADMIN_NOTIFY_PHONES=5511111111111,5511222222222
NOTIFY_QUEUE_BATCH=5
NOTIFY_LONG_WAIT_MINUTES=15
NOTIFY_IMMEDIATE_ON_HANDOVER=true
NOTIFY_ON_ASSUMIR=true
DAILY_SUMMARY_HOUR=20
WHATBOT_TIMEZONE=America/Sao_Paulo
```

**Alertas automáticos:**
- Imediato a cada handover
- Lista completa a cada N handovers
- Espera prolongada (> X min)
- Resumo diário após `DAILY_SUMMARY_HOUR`
- Auto-atendido quando secretaria responde pelo WhatsApp Business

**Comandos admin:** `fila`, `assumir NUMERO`, `atender NUMERO`, `reativar NUMERO`, `resumo`, `ajuda`

Jobs agendados no Windmill (recomendado a cada 5 min): `f/whatbot/check_queue`
