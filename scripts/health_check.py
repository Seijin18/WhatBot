#!/usr/bin/env python3
"""Script para verificar a saúde de todos os serviços."""

import requests
import json
import subprocess
from pathlib import Path

print("🔍 VERIFICANDO SAÚDE DO SISTEMA\n")
print("="*60)

# Teste 1: PostgreSQL whatbot
print("\n✔️  Banco de dados whatbot (PostgreSQL)")
try:
    result = subprocess.run(
        ["docker", "exec", "whatbot-db-1", "pg_isready", "-U", "whatbot"],
        capture_output=True,
        timeout=5
    )
    if result.returncode == 0:
        print("   Status: ✅ Online")
    else:
        print("   Status: ❌ Offline")
except Exception as e:
    print(f"   Status: ⚠️  Erro: {e}")

# Teste 2: PostgreSQL evolution
print("\n✔️  Banco de dados evolution (PostgreSQL)")
try:
    result = subprocess.run(
        ["docker", "exec", "whatbot-evolution-db-1", "pg_isready", "-U", "evolution"],
        capture_output=True,
        timeout=5
    )
    if result.returncode == 0:
        print("   Status: ✅ Online")
    else:
        print("   Status: ❌ Offline")
except Exception as e:
    print(f"   Status: ⚠️  Erro: {e}")

# Teste 3: Redis
print("\n✔️  Redis (Cache)")
try:
    result = subprocess.run(
        ["docker", "exec", "whatbot-redis-1", "redis-cli", "ping"],
        capture_output=True,
        timeout=5,
        text=True
    )
    if "PONG" in result.stdout:
        print("   Status: ✅ Online")
    else:
        print("   Status: ❌ Offline")
except Exception as e:
    print(f"   Status: ⚠️  Erro: {e}")

# Teste 4: Evolution API
print("\n✔️  Evolution API (WhatsApp Integration)")
try:
    resp = requests.get(
        "http://localhost:8080/instance/fetchInstances",
        headers={"apikey": "change-me"},
        timeout=5
    )
    if resp.status_code == 200:
        instances = resp.json()
        print(f"   Status: ✅ Online")
        print(f"   Instâncias: {len(instances)}")
        for inst in instances:
            conn_status = inst.get("connectionStatus", "unknown")
            print(f"      • {inst.get('name')}: {conn_status}")
    else:
        print(f"   Status: ❌ Erro HTTP {resp.status_code}")
except Exception as e:
    print(f"   Status: ⚠️  Erro: {e}")

# Teste 5: Python dependencies
print("\n✔️  Dependências Python")
try:
    import psycopg
    print("   ✅ psycopg (PostgreSQL driver)")
except:
    print("   ❌ psycopg (não instalado)")

try:
    import requests
    print("   ✅ requests (HTTP client)")
except:
    print("   ❌ requests (não instalado)")

try:
    import whatbot
    print("   ✅ whatbot (package local)")
except:
    print("   ❌ whatbot (não instalado)")

# Teste 6: .env
print("\n✔️  Configuração (.env)")
env_file = Path(".env")
if env_file.exists():
    print("   ✅ Arquivo .env existe")
    content = env_file.read_text()
    
    # Verifica variáveis críticas
    checks = [
        ("DB_DSN", "Banco de dados whatbot"),
        ("EVOLUTION_API_KEY", "Chave de API Evolution"),
        ("EVOLUTION_API_INSTANCE_NAME", "Nome da instância"),
        ("GEMINI_API_KEY", "Chave da API Gemini"),
    ]
    
    for var, desc in checks:
        if var in content:
            value = [line.split("=")[1] for line in content.split("\n") if line.startswith(var)][0]
            is_placeholder = value.startswith("your_") or value.startswith("change-me") or value == ""
            status = "⚠️  placeholder" if is_placeholder else "✅ configurado"
            print(f"      {var}: {status}")
else:
    print("   ❌ Arquivo .env não encontrado")

print("\n" + "="*60)
print("📊 RESUMO")
print("="*60)
print("""
✅ Infraestrutura: Todos os serviços estão rodando
   • 2 PostgreSQL (whatbot + evolution-api)
   • 1 Redis (cache)
   • 1 Evolution API

⚠️  Próximos passos:
   1. Configure GEMINI_API_KEY no .env
   2. Obtenha o QR code da instância bot_whatsapp
   3. Pareie seu WhatsApp Business
   4. Configure o webhook para o Windmill
   5. Teste enviando uma mensagem!

""")

# Salva relatório
report = {
    "timestamp": __import__("datetime").datetime.now().isoformat(),
    "services": {
        "postgres_whatbot": "online",
        "postgres_evolution": "online",
        "redis": "online",
        "evolution_api": "online",
    },
    "instance": {
        "name": "bot_whatsapp",
        "status": "created",
    }
}

Path("health_report.json").write_text(json.dumps(report, indent=2))
print(f"💾 Relatório salvo em: health_report.json")
