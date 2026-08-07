#!/bin/bash

# Script para subir um túnel público (cloudflared) até o whatbot-ingress,
# no mesmo padrão de start-whatbot.sh — roda em background, com PID/log
# próprios. Necessário porque a WhatsApp Cloud API só entrega webhooks numa
# URL pública, e o "quick tunnel" gratuito do Cloudflare troca de URL a cada
# reinício (ver docs/INSTAGRAM_INTEGRATION_PLAN.md) — não é uma solução
# permanente, só o suficiente para desenvolvimento/homologação.
#
# Uso: ./start-tunnel.sh [porta]   (padrão: 8090, mesmo de IG_INGRESS_PORT)

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8090}"
LOG_FILE="$PROJECT_DIR/tunnel.log"
PID_FILE="$PROJECT_DIR/.tunnel-pid"
URL_FILE="$PROJECT_DIR/.tunnel-url"

if ! command -v cloudflared > /dev/null 2>&1; then
    echo "❌ cloudflared não encontrado no PATH deste host."
    echo "   Instale: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
    exit 1
fi

# Já rodando (mesmo PID vivo)? Não duplica.
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "⚠️  Já existe um túnel rodando (PID $OLD_PID)."
        if [ -f "$URL_FILE" ]; then
            echo "   URL: $(cat "$URL_FILE")"
        fi
        exit 0
    fi
    rm -f "$PID_FILE"
fi

echo "🚇 Iniciando túnel cloudflared para http://localhost:$PORT ..."
nohup cloudflared tunnel --url "http://localhost:$PORT" > "$LOG_FILE" 2>&1 &
PID=$!
echo $PID > "$PID_FILE"

# Aguarda a URL aparecer no log (a mesma regex que whatbot/tunnel_control.py usa).
URL=""
for _ in $(seq 1 20); do
    sleep 1
    URL=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$LOG_FILE" | head -n1)
    if [ -n "$URL" ]; then
        break
    fi
done

if ! ps -p "$PID" > /dev/null 2>&1; then
    echo "❌ Erro ao iniciar o túnel — processo morreu logo em seguida."
    cat "$LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi

if [ -z "$URL" ]; then
    echo "⚠️  Túnel iniciado (PID $PID), mas a URL ainda não apareceu no log."
    echo "   Confira em alguns segundos: tail -f $LOG_FILE"
    exit 0
fi

echo "$URL" > "$URL_FILE"
echo "✅ Túnel ativo!"
echo "   PID: $PID"
echo "   URL: $URL"
echo ""
echo "Cole isto no Callback URL do webhook do WhatsApp na Meta:"
echo "   $URL/webhook/whatsapp"
echo ""
echo "Para parar:"
echo "   ./stop-tunnel.sh"
