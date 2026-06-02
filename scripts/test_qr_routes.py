#!/usr/bin/env python3
"""Script para testar diferentes rotas para obter QR code."""

import requests

BASE_URL = "http://localhost:8080"
API_KEY = "change-me"
INSTANCE = "bot_whatsapp"

headers = {"apikey": API_KEY}

# Tenta diferentes rotas
rotas = [
    f"/instance/connect/qr-code/{INSTANCE}",
    f"/instance/{INSTANCE}/qrcode",
    f"/instance/{INSTANCE}/connect",
    f"/qrcode/{INSTANCE}",
    f"/auth/qr-code/{INSTANCE}",
    f"/baileysqrcode/{INSTANCE}",
]

print(f"🔍 Testando diferentes rotas para QR code...\n")

for rota in rotas:
    url = f"{BASE_URL}{rota}"
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"Rota: {rota}")
        print(f"Status: {resp.status_code}")
        
        if resp.status_code == 200:
            print(f"✅ Funciona! Response: {resp.json()}\n")
        else:
            print(f"❌ {resp.status_code}\n")
    except Exception as e:
        print(f"Rota: {rota}")
        print(f"❌ Erro: {str(e)[:100]}\n")
