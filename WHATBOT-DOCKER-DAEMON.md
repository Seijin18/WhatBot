# WhatBot Docker Daemon — Scripts para rodar em Background

Estes scripts permitem rodar WhatBot em background sem terminal aberto.

## 📋 Arquivos

- `start-whatbot.sh` — Inicia WhatBot em background
- `stop-whatbot.sh` — Para WhatBot de forma limpa
- `status-whatbot.sh` — Verifica status e mostra últimos logs

## 🚀 Como usar

### 1. Copie os scripts para o diretório do projeto

```bash
# A partir de onde você baixou os scripts:
cp start-whatbot.sh stop-whatbot.sh status-whatbot.sh ~/Projects/WhatBot/
cd ~/Projects/WhatBot
chmod +x start-whatbot.sh stop-whatbot.sh status-whatbot.sh
```

### 2. Inicie WhatBot

```bash
./start-whatbot.sh
```

**Resultado:**
```
🚀 Iniciando WhatBot...
✅ WhatBot iniciado com sucesso!
   PID: 12345
   Logs: /home/seu-usuario/Projects/WhatBot/whatbot.log

Para ver os logs:
   tail -f whatbot.log

Para parar:
   ./stop-whatbot.sh
```

### 3. Verifique o status a qualquer momento

```bash
./status-whatbot.sh
```

**Resultado:**
```
📊 Status do WhatBot
===================

✅ WhatBot está RODANDO
   PID: 12345

Processo:
user  12345  1.2  5.3 1234567 890123 ?  Ssl  10:30  0:45 docker-compose up

Containers:
CONTAINER ID   IMAGE                    STATUS
a1b2c3d4e5f6   postgres:15              Up 15 minutes
f6e5d4c3b2a1   redis:7-alpine           Up 15 minutes

Últimas 20 linhas do log:
========================
[+] Running 6/6
 ✔ Container whatbot-db-1              Started
 ✔ Container whatbot-evolution-db-1    Started
 ✔ Container whatbot-redis-1           Started
...
```

### 4. Pare WhatBot

```bash
./stop-whatbot.sh
```

## 🔍 Rastreando o processo

Como o nome do processo é claramente identificável, você pode:

### Ver todos os processos relacionados:
```bash
ps aux | grep docker-compose
```

### Ver o PID armazenado:
```bash
cat .whatbot-pid
```

### Matar manualmente se necessário:
```bash
kill $(cat .whatbot-pid)
# Ou com força bruta:
pkill -f "docker-compose up"
```

## 📊 Monitorando logs

### Ver logs em tempo real:
```bash
tail -f whatbot.log
```

### Ver últimas 50 linhas:
```bash
tail -50 whatbot.log
```

### Buscar erros:
```bash
grep -i error whatbot.log
```

## ⚙️ Configuração automática no boot (Opcional)

Se quiser que WhatBot inicie automaticamente ao ligar o computador:

### Opção 1: Adicionar ao crontab (simples)

```bash
crontab -e
```

Adicione a linha:
```
@reboot /home/seu-usuario/Projects/WhatBot/start-whatbot.sh
```

### Opção 2: Criar um systemd service (mais profissional)

Crie `/etc/systemd/system/whatbot.service`:

```ini
[Unit]
Description=WhatBot Docker Daemon
After=network.target docker.service
Wants=docker.service

[Service]
Type=forking
User=seu-usuario
WorkingDirectory=/home/seu-usuario/Projects/WhatBot
ExecStart=/home/seu-usuario/Projects/WhatBot/start-whatbot.sh
ExecStop=/home/seu-usuario/Projects/WhatBot/stop-whatbot.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Então:
```bash
sudo systemctl daemon-reload
sudo systemctl enable whatbot
sudo systemctl start whatbot

# Verificar:
sudo systemctl status whatbot
```

## 💡 Dicas

- **Os scripts usam `nohup`**: o docker-compose continua rodando mesmo que o terminal seja fechado
- **Logs são salvos em `whatbot.log`**: fácil de revisar e debugar
- **O PID é armazenado em `.whatbot-pid`**: permite parar de forma limpa
- **Nome do processo é identificável**: procure por "docker-compose" se precisar matar manualmente

## 🐛 Troubleshooting

### "docker-compose: command not found"
```bash
# Use docker compose (sem hífen) em versões recentes:
# Edite start-whatbot.sh e mude "docker-compose" para "docker compose"
sed -i 's/docker-compose/docker compose/g' start-whatbot.sh
```

### WhatBot não inicia
```bash
# Verifique o log:
tail -100 whatbot.log

# Rode manualmente para ver erros:
docker compose up
```

### Processo "zumbi" que não morre
```bash
# Force kill:
pkill -9 -f "docker-compose up"
docker compose down --remove-orphans
```

## 🚇 Túnel público (webhook da WhatsApp Cloud API / Instagram)

`start-tunnel.sh` / `stop-tunnel.sh` — mesmo padrão dos scripts acima,
para subir um túnel `cloudflared` (quick tunnel gratuito) até o
`whatbot-ingress` (porta `IG_INGRESS_PORT`, padrão 8090). Necessário
porque a Meta só entrega webhooks numa URL pública, e esses túneis
gratuitos trocam de URL a cada reinício — não é solução permanente, só o
suficiente para desenvolvimento/homologação (ver
`docs/INSTAGRAM_INTEGRATION_PLAN.md` para as alternativas com domínio
fixo).

```bash
./start-tunnel.sh          # porta 8090 por padrão
./start-tunnel.sh 8091     # ou outra porta

# ✅ Túnel ativo!
#    PID: 12345
#    URL: https://exemplo-aleatorio.trycloudflare.com
#
# Cole isto no Callback URL do webhook do WhatsApp na Meta:
#    https://exemplo-aleatorio.trycloudflare.com/webhook/whatsapp

./stop-tunnel.sh
```

Toda vez que a URL mudar (reinício do túnel), é preciso colar a nova URL
de novo no painel da Meta (App Dashboard → WhatsApp/Instagram →
Configuração → Webhooks) — o *verify token* (`WA_CLOUD_WEBHOOK_VERIFY_TOKEN`/
`IG_WEBHOOK_VERIFY_TOKEN`) não muda.

O botão "Iniciar túnel" no visualizador temporário de conversas
(`http://localhost:8090/admin/ui`) faz a mesma coisa por dentro do
próprio container `whatbot-ingress` (`whatbot/tunnel_control.py`), sem
precisar rodar esses scripts manualmente — os dois mecanismos
compartilham o arquivo `.tunnel-url` na raiz do projeto como fonte única
de "qual é a URL pública atual".
