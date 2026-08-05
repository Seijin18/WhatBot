#!/bin/bash

# Script para parar WhatBot de forma limpa
# Coloque este arquivo no diretório do projeto e execute: ./stop-whatbot.sh

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$PROJECT_DIR/.whatbot-pid"

echo "🛑 Parando WhatBot..."

# Tenta parar via docker compose primeiro (mais limpo)
if [ -d "$PROJECT_DIR" ] && [ -f "$PROJECT_DIR/docker-compose.yml" ]; then
    cd "$PROJECT_DIR"
    docker compose down 2>/dev/null
fi

# Mata o processo se ainda estiver rodando
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null 2>&1; then
        kill $PID 2>/dev/null
        sleep 1
        if ps -p $PID > /dev/null 2>&1; then
            kill -9 $PID 2>/dev/null
        fi
    fi
    rm "$PID_FILE"
fi

# Mata qualquer processo docker compose remanescente
pkill -f "docker compose up" 2>/dev/null

echo "✅ WhatBot parado"
echo ""
echo "Para verificar status:"
echo "   ps aux | grep docker-compose"
