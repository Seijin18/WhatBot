#!/usr/bin/env python3
"""Script para aguardar e obter o QR code quando gerado."""

import requests
import json
import time
from pathlib import Path

BASE_URL = "http://localhost:8080"
API_KEY = "change-me"
INSTANCE = "bot_whatsapp"

headers = {"apikey": API_KEY}

print(f"⏳ Aguardando geração do QR code (até 15 segundos)...\n")

for tentativa in range(1, 16):
    try:
        # Tenta diferentes rotas
        urls = [
            f"{BASE_URL}/instance/{INSTANCE}",
            f"{BASE_URL}/instance/{INSTANCE}/qrcode",
            f"{BASE_URL}/instance/fetchInstances",
        ]
        
        for url in urls:
            try:
                resp = requests.get(url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    result = resp.json()
                    
                    # Se é uma lista, procura pela instância
                    if isinstance(result, list):
                        for inst in result:
                            if inst.get("name") == INSTANCE:
                                if "qrcode" in inst and inst["qrcode"]:
                                    print(f"✅ QR code encontrado!")
                                    print(f"URL da instância: {url}")
                                    print(json.dumps(inst, indent=2))
                                    
                                    # Tenta salvar o QR se estiver em base64
                                    if isinstance(inst["qrcode"], str) and inst["qrcode"].startswith("data:image"):
                                        # É uma data URL
                                        base64_part = inst["qrcode"].split(",")[1] if "," in inst["qrcode"] else inst["qrcode"]
                                        Path("qrcode.txt").write_text(base64_part)
                                        print(f"💾 QR code salvo")
                                    
                                    exit(0)
                    # Se é dict
                    elif isinstance(result, dict):
                        if "qrcode" in result and result["qrcode"]:
                            if isinstance(result["qrcode"], dict) and "base64" in result["qrcode"]:
                                print(f"✅ QR code encontrado!")
                                print(f"URL: {url}")
                                qr_base64 = result["qrcode"]["base64"]
                                Path("qrcode.txt").write_text(qr_base64)
                                print(f"💾 QR code salvo")
                                exit(0)
            except:
                pass
        
        print(f"Tentativa {tentativa}/15 - QR code ainda não gerado")
        time.sleep(1)
        
    except Exception as e:
        print(f"Erro: {e}")

print("\n❌ QR code não foi gerado no tempo esperado")
print("\nDica: Tente também fazer uma requisição WebSocket ou verificar a documentação de endpoints da Evolution API")
