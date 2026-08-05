# 🤖 WhatBot - Assistente Automático WhatsApp com Gemini

Sistema completo para atender automaticamente clientes que entram em contato pelo WhatsApp Business usando IA Gemini integrada com Evolution API e Windmill.

## 📋 Visão Geral

```
┌─────────────────────────────────────────────────────────┐
│                   ARQUITETURA COMPLETA                  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  WhatsApp Business                                     │
│         │                                              │
│         ▼                                              │
│  Evolution API (Port 8080)                            │
│  └─ Webhook Listener                                  │
│  └─ QR Code Pairing                                   │
│  └─ Message Management                                │
│         │                                              │
│         ▼                                              │
│  Windmill (External)                                  │
│  └─ Orquestra workflow                                │
│  └─ Chama whatbot.main()                              │
│         │                                              │
│         ▼                                              │
│  whatbot (Python App)                                 │
│  ├─ Domain Layer (regras de negócio)                 │
│  ├─ DB Layer (PostgreSQL)                            │
│  ├─ Gemini Client (IA)                               │
│  └─ Evolution Client (envio de resposta)             │
│         │                                              │
│    ┌────┼────┐                                        │
│    ▼    ▼    ▼                                        │
│   DB  Redis Cache                                    │
│    
└─────────────────────────────────────────────────────────┘
```

## 🚀 Status Atual

✅ **SISTEMA PRONTO PARA OPERAÇÃO**

- ✅ Docker Compose configurado com todos os serviços
- ✅ Banco de dados PostgreSQL separados (whatbot + evolution-api)
- ✅ Redis para cache e sessões
- ✅ Evolution API integrada (v2.1.1)
- ✅ Modulo Python whatbot com Clean Architecture
- ✅ Gemini SDK (google-genai) com fallback
- ✅ Testes unitários passando (5/5)
- ⏳ **Aguardando**: Parear WhatsApp Business + configurar Windmill

## 🛠️ Serviços em Execução

| Serviço | Porta | Status | Descrição |
|---------|-------|--------|-----------|
| Evolution API | 8080 | ✅ Online | WhatsApp Integration |
| PostgreSQL (whatbot) | 5432 | ✅ Online | BD do bot |
| PostgreSQL (evolution-api) | (interno) | ✅ Online | BD da Evolution |
| Redis | 6379 | ✅ Online | Cache & Sessões |
| whatbot | - | ⏳ Aguardando | Roda via Windmill webhook |

### Verificar Status
```bash
# Verificação automática completa
python scripts/health_check.py

# Listar instâncias de WhatsApp
curl.exe -H "apikey: change-me" http://localhost:8080/instance/fetchInstances
```

## 📱 Passo 1: Parear WhatsApp Business

A instância `bot_whatsapp` já foi criada. Agora você precisa obter o QR code:

### Opção A: Via Dashboard Evolution API
1. Abra `http://localhost:8080` em seu navegador
2. Autentique com: `apikey: change-me`
3. Localize a instância `bot_whatsapp`
4. Clique em "Conectar" para gerar o QR code
5. Escaneie com seu WhatsApp Business (celular)

### Opção B: Via API HTTP
```bash
# Obter detalhes da instância
curl.exe -H "apikey: change-me" http://localhost:8080/instance/bot_whatsapp

# Procurar pela propriedade "qrcode" na resposta
# Se vazio, aguarde alguns segundos e tente novamente
# Quando gerar, será um base64 que você pode visualizar em https://base64toimage.com/
```

### Opção C: Verificar Parenciamento
```bash
# Listar instâncias
curl.exe -H "apikey: change-me" http://localhost:8080/instance/fetchInstances

# Procure por:
# - connectionStatus: "open" (conectado)
# - ownerJid: seu número WhatsApp (ex: "5511999999999@s.whatsapp.net")
```

⏱️ **Quando a instância estiver `close`** → QR code expirou, gere novamente  
✅ **Quando a instância estiver `open`** → WhatsApp pareado com sucesso!

## 🔁 Alternativa: WhatsApp Cloud API (oficial da Meta)

A Evolution API (Baileys, passos acima) é uma integração não-oficial e está
sujeita a instabilidades fora do nosso controle — por exemplo o erro
`status: 0` / `messageStubParameters: ["463"]` (`NackCallerReachoutTimelocked`,
um rate-limit de privacidade do WhatsApp), reportado como bug aberto em
[evolution-foundation/evolution-api#2653](https://github.com/evolution-foundation/evolution-api/issues/2653).
Para evitar essa classe de problema, o bot também suporta a **API oficial da
Meta** (WhatsApp Cloud API) como provedor alternativo, sob o mesmo canal
`"whatsapp"` — ver `openspec/changes/whatsapp-cloud-channel-client/`.

### Pré-requisitos (feitos no Meta Business Manager, fora do código)

1. App na Meta com o produto **WhatsApp** ativado (developers.facebook.com).
2. Um número de telefone verificado, com seu `phone_number_id`.
3. Um **System User token** de longa duração (não expira como o token de
   teste de 24h) com permissão `whatsapp_business_messaging`.
4. Webhook configurado no painel da Meta apontando para
   `https://<seu-domínio-público>/webhook/whatsapp`, com o mesmo
   `WA_CLOUD_WEBHOOK_VERIFY_TOKEN` que você vai colocar no `.env` — mesmo
   fluxo `hub.challenge` já usado pelo Instagram (ver
   `whatbot/ingress.py`), servido por `whatbot_ingress`
   (`docker compose --profile instagram up whatbot-ingress`, ou o serviço
   equivalente já rodando).

### Configuração no WhatBot

```bash
# .env
WHATSAPP_PROVIDER=cloud
WA_CLOUD_APP_SECRET=<App Secret do app na Meta>
WA_CLOUD_WEBHOOK_VERIFY_TOKEN=<token arbitrário, o mesmo cadastrado no painel da Meta>
```

E popular `canal_credenciais` com o token de sistema e o `phone_number_id`
(não precisa de fluxo OAuth como o Instagram — é um token direto):

```sql
INSERT INTO canal_credenciais (canal, account_id, access_token)
VALUES ('whatsapp', '<phone_number_id>', '<system_user_token>')
ON CONFLICT (canal) DO UPDATE
SET account_id = EXCLUDED.account_id, access_token = EXCLUDED.access_token;
```

Reinicie o processo do bot depois de alterar `WHATSAPP_PROVIDER` ou
`canal_credenciais` — `_init_infra()` só resolve o provedor uma vez, na
subida do processo.

⚠️ **`WHATSAPP_PROVIDER=cloud` sem credencial em `canal_credenciais` falha
alto no startup** (`RuntimeError`), de propósito — WhatsApp é o canal padrão
do bot, então uma credencial ausente é erro de configuração, não uma
feature opcional desligada (diferente do Instagram, que só fica sem canal
registrado silenciosamente).

Voltar para `WHATSAPP_PROVIDER=evolution` (ou simplesmente remover a
variável) restaura o comportamento atual, sem precisar reverter código.

## 🔌 Passo 2: Configurar Webhook no Windmill

Após parear seu WhatsApp, configure o webhook da Evolution API:

### Registrar Webhook
```bash
curl.exe -X POST "http://localhost:8080/webhook/set/bot_whatsapp" `
  -H "apikey: change-me" `
  -H "Content-Type: application/json" `
  -d '{
    "url": "https://seu-windmill.com/webhook/chatbot",
    "webhook_by_events": false,
    "events": ["MESSAGES_UPSERT", "MESSAGES_UPDATE"],
    "headers": {
      "Authorization": "Bearer seu_token_windmill"
    }
  }'
```

Substitua:
- `https://seu-windmill.com/webhook/chatbot` → seu endpoint Windmill
- `seu_token_windmill` → token de autenticação do Windmill (opcional)

### Testar Webhook (opcional)
```bash
curl.exe -X POST "http://localhost:8080/instance/messages/send/bot_whatsapp" `
  -H "apikey: change-me" `
  -H "Content-Type: application/json" `
  -d '{
    "number": "seu_numero_whatsapp",
    "text": "Olá! Este é um teste."
  }'
```

## ⚙️ Passo 3: Configurar Credenciais

Edite o arquivo `.env` com suas chaves reais:

```bash
# Sua chave da API Google Gemini (obtida em https://aistudio.google.com/)
GEMINI_API_KEY=seu_gemini_key_aqui

# Evolução (já configurada)
EVOLUTION_API_KEY=change-me
EVOLUTION_API_INSTANCE_NAME=bot_whatsapp

# Banco de dados (já configurados)
DB_DSN=postgresql://whatbot:whatbot@db:5432/whatbot
DATABASE_CONNECTION_URI=postgresql://evolution:evolution@evolution-db:5432/evolution?schema=public
```

### Obter GEMINI_API_KEY
1. Vá para https://aistudio.google.com/
2. Clique em "Get API Key"
3. Crie uma nova chave
4. Copie e cole no `.env`

## 📝 Passo 4: Configurar Entrypoint no Windmill

No Windmill, crie um novo **Script Python** com:

### Nome
```
whatbot_handler
```

### Código
```python
import requests
import json

# URL da sua API whatbot (se rodando localmente via Docker)
WHATBOT_API = "http://localhost:5000"

def main(payload: dict) -> dict:
    """
    Entrypoint Windmill para chatbot WhatBot
    
    Args:
        payload: {
            "from_number": "5511999999999",
            "text": "Olá, como funciona?",
            "timestamp": 1234567890,
            ...
        }
    """
    
    # Se whatbot roda como container:
    # import subprocess
    # result = subprocess.run(
    #     ["python", "-m", "whatbot.main"],
    #     input=json.dumps(payload),
    #     capture_output=True,
    #     text=True
    # )
    # return json.loads(result.stdout)
    
    # Ou importar diretamente:
    from whatbot.main import main as whatbot_main
    return whatbot_main(payload)
```

### Configurar como Webhook
1. Em "Webhook", ative
2. Configure para aceitar POST
3. Copie a URL de webhook
4. Cole na configuração Evolution API (passo anterior)

## 💬 Passo 5: Teste o Sistema

### Teste Local (sem WhatsApp)
```bash
# Executar directamente com um payload de teste
python -m whatbot.main '{"from_number": "5511999999999", "text": "Olá"}'

# Ou usar o script de teste:
python scripts/test_whatbot.py
```

### Teste com WhatsApp
1. Envie uma mensagem para o número do WhatsApp Business pareado
2. Você deve receber uma resposta automaticamente
3. Verifique os logs do bot:
```bash
docker logs whatbot -f  # Se rodar via Docker
```

## 🏗️ Estrutura do Projeto

```
WhatBot/
├── whatbot/              # Package principal (Clean Architecture)
│   ├── __init__.py
│   ├── config.py        # Variáveis de ambiente e prompts
│   ├── db.py            # Camada de dados (PostgreSQL)
│   ├── whatsapp.py      # Cliente Evolution API
│   ├── gemini_client.py  # Wrapper Gemini
│   ├── domain.py        # Regras de negócio puras
│   └── main.py          # Entrypoint Windmill
│
├── tests/               # Testes unitários
│   └── test_domain.py  # Testes de domínio (5/5 passando)
│
├── scripts/             # Utilitários
│   ├── health_check.py
│   ├── get_qrcode.py
│   ├── create_instance.py
│   ├── delete_and_recreate.py
│   └── test_auth.py
│
├── docker-compose.yml   # Orquestração de containers
├── Dockerfile          # Build do app Python
├── requirements.txt    # Dependências Python
├── .env               # Variáveis de ambiente
├── .env.example       # Exemplo de .env
├── .dockerignore
└── README.md          # Este arquivo
```

## 🧪 Executar Testes

```bash
# Executar testes unitários
python -m unittest discover -s tests -p 'test_*.py' -v

# Resultado esperado: 5 testes, todos passando (OK)
```

## 📊 Logs e Debug

### Verificar Evolution API
```bash
docker logs evolution_api -f --tail 50
```

### Verificar Banco de Dados
```bash
# Conectar ao PostgreSQL whatbot
docker exec -it whatbot-db-1 psql -U whatbot -d whatbot

# Ver tabelas
\dt

# Ver contatos
SELECT * FROM contacts;

# Ver mensagens
SELECT * FROM messages ORDER BY created_at DESC;
```

### Verificar Redis
```bash
docker exec -it whatbot-redis-1 redis-cli
PING
KEYS *
```

## 🔐 Variáveis de Ambiente Críticas

| Variável | Obrigatória | Padrão | Descrição |
|----------|-------------|--------|-----------|
| `GEMINI_API_KEY` | ✅ SIM | - | Chave da API Google Gemini |
| `EVOLUTION_API_KEY` | ✅ SIM | `change-me` | Chave de autenticação Evolution |
| `EVOLUTION_API_INSTANCE_NAME` | ✅ SIM | `bot_whatsapp` | Nome da instância WhatsApp |
| `DB_DSN` | ✅ SIM | postgresql://... | String de conexão PostgreSQL |
| `GEMINI_MODEL` | ❌ NÃO | `gemini-1.5-flash-lite` | Modelo a usar |
| `GEMINI_TEMPERATURE` | ❌ NÃO | `0.1` | Criatividade (0-1) |

## 🚨 Troubleshooting

### "Evolution API returns 403 Forbidden"
```
❌ Problema: apikey inválida
✅ Solução: Verificar que o header é "apikey: change-me"
           Não use "Authorization" ou "X-API-Key"
```

### "GEMINI_API_KEY not configured"
```
❌ Problema: Chave não foi preenchida no .env
✅ Solução: Obter chave em https://aistudio.google.com/
           Adicionar ao .env e reiniciar containers
```

### "Instância não pareada"
```
❌ Problema: connectionStatus = "close"
✅ Solução: 
   1. Obter novo QR code
   2. Escanear com WhatsApp Business
   3. Aguardar até 30 segundos
   4. Verificar status novamente
```

### "Mensagem enviada aparece OK nos logs mas nunca chega no WhatsApp" (erro 463)
```
❌ Problema: Evolution API loga "Sending message to ..." e status 200, mas o
           WhatsApp do destinatário nunca recebe. No log da Evolution API
           aparece "status": 0, "messageStubParameters": ["463"].
🔍 Causa: erro 463 (NackCallerReachoutTimelocked) — rate-limit de privacidade
         do próprio WhatsApp, comum logo após repareamento de sessão via QR
         code. Bug conhecido do Baileys/Evolution API, não é um problema do
         whatbot — ver evolution-foundation/evolution-api#2653.
✅ Solução:
   1. Evitar deletar/recriar a instância repetidamente — cada repareamento
      reinicia o time-lock.
   2. Esperar (minutos a poucas horas) e testar de novo.
   3. Se persistir, considerar migrar para a WhatsApp Cloud API oficial
      (seção "Alternativa: WhatsApp Cloud API" acima), que não tem essa
      classe de bug.
```

### "Database connection failed"
```
❌ Problema: Erro ao conectar PostgreSQL
✅ Solução:
   docker compose restart db evolution-db
   docker logs whatbot-db-1
```

### "Module 'google.generativeai' not found"
```
❌ Problema: SDK antigo
✅ Solução: Dependências já atualizadas para google-genai
           pip install -r requirements.txt
```

## 📞 Suporte

Para erros ou dúvidas:

1. Verifique a saúde do sistema: `python scripts/health_check.py`
2. Consulte os logs: `docker logs <container_name>`
3. Teste endpoints isoladamente: scripts em `scripts/`
4. Valide o `.env`: todas as variáveis obrigatórias preenchidas

## 📚 Referências

- [Evolution API Docs](https://doc.evolution-api.com)
- [Google Gemini API](https://ai.google.dev)
- [Windmill Docs](https://windmill.dev)
- [Python psycopg](https://www.psycopg.org)

## 📄 Licença

Projeto desenvolvido para fins educacionais e comerciais.

---

**Última atualização**: 2026-06-01  
**Status**: ✅ Pronto para Produção (aguardando Windmill + WhatsApp pairing)
