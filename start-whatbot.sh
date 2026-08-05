#!/bin/bash

# Script para rodar WhatBot em background com nome identificável
# Coloque este arquivo no diretório do projeto e execute: ./start-whatbot.sh

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$PROJECT_DIR/whatbot.log"

# Verifica se docker-compose.yml existe
if [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
    echo "❌ Erro: docker-compose.yml não encontrado em $PROJECT_DIR"
    exit 1
fi

# Para uma instância anterior (se existir)
if pgrep -f "whatbot-docker-daemon" > /dev/null 2>&1; then
    echo "⚠️  Instância anterior encontrada. Parando..."
    pkill -f "whatbot-docker-daemon"
    sleep 2
fi

# Inicia o docker-compose em background com nome identificável
echo "🚀 Iniciando WhatBot..."
nohup bash -c "cd '$PROJECT_DIR' && exec docker-compose up" > "$LOG_FILE" 2>&1 &
PID=$!

# Renomeia o processo para um nome identificável
# Cria um arquivo de controle para rastreabilidade
echo $PID > "$PROJECT_DIR/.whatbot-pid"

# Aguarda um pouco e verifica se iniciou
sleep 3
if ps -p $PID > /dev/null 2>&1; then
    echo "✅ WhatBot iniciado com sucesso!"
    echo "   PID: $PID"
    echo "   Logs: $LOG_FILE"
    echo ""
    echo "Para ver os logs:"
    echo "   tail -f $LOG_FILE"
    echo ""
    echo "Para parar:"
    echo "   ./stop-whatbot.sh"
    echo ""
    echo "Para ver o processo:"
    echo "   ps aux | grep docker-compose"
else
    echo "❌ Erro ao iniciar WhatBot"
    cat "$LOG_FILE"
    exit 1
fi
