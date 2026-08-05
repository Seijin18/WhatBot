@echo off
:: WhatBot Docker Startup Script
:: Roda docker-compose em background com processo identificável
:: Salve este arquivo na raiz do projeto WhatBot

setlocal enabledelayedexpansion

:: Verifica se o Docker está rodando
docker ps >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Docker Desktop nao esta rodando!
    echo Por favor, inicie o Docker Desktop antes de executar este script.
    pause
    exit /b 1
)

:: Define o caminho absoluto do projeto
cd /d "%~dp0"

echo [INFO] Iniciando WhatBot Docker Compose...
echo [INFO] Diretorio: %cd%

:: Roda docker-compose em background usando PowerShell
:: O processo sera nomeado como "WhatBot-Docker" para facilitar identificacao
powershell -NoProfile -WindowStyle Hidden -Command ^
    "Start-Process -FilePath 'docker' -ArgumentList 'compose up' -NoNewWindow -PassThru | ForEach-Object { $_.ProcessName = 'WhatBot-Docker' }" ^
    >nul 2>&1

if errorlevel 1 (
    echo [ERRO] Falha ao iniciar Docker Compose
    pause
    exit /b 1
)

echo [SUCESSO] WhatBot Docker iniciado em background!
echo.
echo Para PARAR o servico, use um dos metodos:
echo   1. Gerenciador de Tarefas ^(Ctrl+Shift+Esc^) ^> Processos ^> docker.exe ^> Finalizar
echo   2. PowerShell como Admin e execute:
echo      taskkill /IM docker.exe /F
echo   3. Ou use o script 'stop-whatbot-docker.bat' se criado
echo.
echo Para VER os LOGS:
echo   - Docker Desktop ^> Containers ^> whatbot
echo   - OU execute: docker compose logs -f
echo.
timeout /t 3 /nobreak
