#!/usr/bin/env python3
"""Script para recriar a instância e obter QR code na resposta."""

import requests
import json
from pathlib import Path

BASE_URL = "http://localhost:8080"
API_KEY = "change-me"

headers = {
    "apikey": API_KEY,
    "Content-Type": "application/json",
}

# Payload para criar instância
payload = {
    "instanceName": "bot_whatsapp",
    "qrcode": True,
}

print(f"📱 Tentando criar/resetar instância 'bot_whatsapp'...")
print(f"🔗 POST {BASE_URL}/instance/create")

try:
    response = requests.post(f"{BASE_URL}/instance/create", 
                            headers=headers, 
                            json=payload, 
                            timeout=10)
    
    print(f"\n📊 Status: {response.status_code}")
    result = response.json()
    print(f"📋 Response:\n{json.dumps(result, indent=2)}")
    
except requests.RequestException as e:
    print(f"❌ Erro: {e}")
