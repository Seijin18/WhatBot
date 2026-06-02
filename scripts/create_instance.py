#!/usr/bin/env python3
"""Script para criar uma instância no Evolution API e exibir o QR code."""

import requests
import json
import sys
from pathlib import Path

# URL da Evolution API
BASE_URL = "http://localhost:8080"
API_KEY = "change-me"

def create_instance(instance_name: str = "bot_whatsapp"):
    """Cria uma instância no Evolution API."""
    url = f"{BASE_URL}/instance/create"
    headers = {
        "apikey": API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "instanceName": instance_name,
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS",
    }
    
    print(f"📱 Criando instância '{instance_name}' na Evolution API...")
    print(f"🔗 URL: {url}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        if response.status_code == 201:
            print("✅ Instância criada com sucesso!")
            print(json.dumps(result, indent=2))
            
            # Salva o QR code se disponível
            if "qrcode" in result and "base64" in result["qrcode"]:
                qr_base64 = result["qrcode"]["base64"]
                qr_file = Path("qrcode.txt")
                qr_file.write_text(qr_base64)
                print(f"\n💾 QR code salvo em: {qr_file.absolute()}")
                print("\n📲 Como usar o QR code:")
                print("   1. Acesse: https://base64toimage.com/")
                print("   2. Cole o conteúdo do arquivo qrcode.txt")
                print("   3. Escaneie a imagem gerada com seu WhatsApp Business")
            
            return result
        else:
            print(f"❌ Erro: {response.status_code}")
            print(json.dumps(result, indent=2))
            return None
            
    except requests.RequestException as e:
        print(f"❌ Erro na requisição: {e}")
        return None

if __name__ == "__main__":
    instance_name = sys.argv[1] if len(sys.argv) > 1 else "bot_whatsapp"
    create_instance(instance_name)
