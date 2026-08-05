#!/bin/bash

# Script para ver status e logs do WhatBot
# Execute: ./status-whatbot.sh

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$PROJECT_DIR/whatbot.log"
PID_FILE="$PROJECT_DIR/.whatbot-pid"

echo "📊 Status do WhatBot"
echo "==================="
echo ""

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null 2>&1; then
        echo "✅ WhatBot está RODANDO"
        echo "   PID: $PID"
        echo ""
        echo "Processo:"
        ps aux | grep -E "docker-compose|docker" | grep -v grep | head -3
    else
        echo "❌ WhatBot NÃO está rodando (PID $PID não encontrado)"
    fi
else
    echo "❌ WhatBot NÃO está rodando (sem arquivo de controle)"
fi

echo ""
echo "Containers:"
docker ps -a --filter "name=whatbot" 2>/dev/null || echo "Docker não disponível"

echo ""
echo "Últimas 20 linhas do log:"
echo "========================"
if [ -f "$LOG_FILE" ]; then
    tail -20 "$LOG_FILE"
else
    echo "(arquivo de log não encontrado)"
fi

echo ""
echo "Comandos úteis:"
echo "  tail -f $LOG_FILE     # Ver logs em tempo real"
echo "  ./stop-whatbot.sh      # Parar"
echo "  docker ps -a           # Ver containers"
