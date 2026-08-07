#!/bin/bash

# Para o túnel cloudflared iniciado por start-tunnel.sh — mesmo padrão de
# stop-whatbot.sh.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$PROJECT_DIR/.tunnel-pid"
URL_FILE="$PROJECT_DIR/.tunnel-url"

echo "🛑 Parando túnel..."

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        kill "$PID" 2>/dev/null
        sleep 1
        if ps -p "$PID" > /dev/null 2>&1; then
            kill -9 "$PID" 2>/dev/null
        fi
    fi
    rm -f "$PID_FILE"
fi

# Mata qualquer cloudflared remanescente apontando para este host (fallback,
# caso o PID_FILE esteja desatualizado).
pkill -f "cloudflared tunnel --url http://localhost:" 2>/dev/null

rm -f "$URL_FILE"
echo "✅ Túnel parado"
