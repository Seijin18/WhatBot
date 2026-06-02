#!/usr/bin/env python3
"""Script para obter QR code de uma instância existente no Evolution API."""

import requests
import json
from pathlib import Path

BASE_URL = "http://localhost:8080"
API_KEY = "change-me"

def get_qrcode(instance_name: str = "bot_whatsapp"):
    """Obtém o QR code de uma instância existente."""
    url = f"{BASE_URL}/instance/connect/qr-code/{instance_name}"
    headers = {"apikey": API_KEY}
    
    print(f"📲 Obtendo QR code da instância '{instance_name}'...")
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        print("✅ QR code obtido com sucesso!")
        
        # Extrai o base64 do QR code
        if "qrcode" in result:
            qr_base64 = result["qrcode"]
            
            # Salva em arquivo
            qr_file = Path("qrcode.txt")
            qr_file.write_text(qr_base64)
            print(f"\n💾 QR code salvo em: {qr_file.absolute()}")
            
            # Salva também em um arquivo HTML para visualizar
            html_content = f'''<!DOCTYPE html>
<html>
<head>
    <title>WhatsApp Bot - QR Code</title>
    <style>
        body {{ font-family: Arial, sans-serif; text-align: center; padding: 20px; }}
        h1 {{ color: #25D366; }}
        img {{ max-width: 400px; margin: 20px 0; }}
        .info {{ background: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0; }}
    </style>
</head>
<body>
    <h1>🤖 WhatsApp Bot - Parear Dispositivo</h1>
    <div class="info">
        <p><strong>Instância:</strong> {instance_name}</p>
        <p>Escaneie o código QR abaixo com seu WhatsApp Business</p>
    </div>
    <img src="data:image/png;base64,{qr_base64}" alt="QR Code">
    <div class="info">
        <p>⏱️ O código QR expira em alguns minutos</p>
        <p>Se expirar, execute novamente este script</p>
    </div>
</body>
</html>'''
            
            html_file = Path("qrcode.html")
            html_file.write_text(html_content)
            print(f"💾 Visualizador HTML salvo em: {html_file.absolute()}")
            print(f"\n🌐 Abra em um navegador: file:///{html_file.absolute()}")
            
            print("\n📱 Instruções:")
            print("   1. Abra o arquivo qrcode.html em seu navegador")
            print("   2. Escaneie o código QR com seu WhatsApp Business")
            print("   3. O bot será automaticamente conectado")
            
            return result
        else:
            print(f"⚠️  Resposta inesperada:")
            print(json.dumps(result, indent=2))
            return None
            
    except requests.RequestException as e:
        print(f"❌ Erro na requisição: {e}")
        return None

def list_instances():
    """Lista todas as instâncias."""
    url = f"{BASE_URL}/instance/fetchInstances"
    headers = {"apikey": API_KEY}
    
    print(f"📋 Listando instâncias...\n")
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        instances = response.json()
        
        if isinstance(instances, list) and len(instances) > 0:
            for idx, inst in enumerate(instances, 1):
                print(f"{idx}. Nome: {inst.get('name')}")
                print(f"   Status: {inst.get('connectionStatus')}")
                print(f"   Token: {inst.get('token')}")
                print(f"   Criada: {inst.get('createdAt')}\n")
        else:
            print("❌ Nenhuma instância encontrada")
            
    except requests.RequestException as e:
        print(f"❌ Erro: {e}")

if __name__ == "__main__":
    list_instances()
    print("\n" + "="*60)
    get_qrcode()
