#!/usr/bin/env python3
"""Script para conectar via WebSocket e obter QR code em tempo real."""

import asyncio
import json
import base64
from pathlib import Path

try:
    import websockets
except ImportError:
    print("❌ websockets não está instalado")
    print("💻 Instale com: pip install websockets")
    exit(1)

WEBSOCKET_URL = "ws://localhost:8080/connect"
INSTANCE_NAME = "bot_whatsapp"

async def connect_and_get_qrcode():
    """Conecta via WebSocket para obter QR code."""
    
    # WebSocket connection string (pode variar)
    ws_url = f"ws://localhost:8080/connect?instance={INSTANCE_NAME}"
    
    print(f"🔌 Conectando ao WebSocket: {ws_url}")
    
    try:
        async with websockets.connect(ws_url) as websocket:
            print(f"✅ Conectado ao WebSocket\n")
            
            while True:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=30)
                    data = json.loads(message)
                    
                    print(f"📨 Evento recebido: {data.get('type', 'unknown')}")
                    
                    # Procura por QR code
                    if data.get("type") == "qr.scanned":
                        print("✅ WhatsApp pareado com sucesso!")
                        break
                    elif "qrcode" in data:
                        qr_data = data.get("qrcode")
                        if qr_data:
                            print(f"✅ QR code gerado!")
                            print(f"📋 Dados: {qr_data[:50]}...")
                            
                            # Salva o QR code
                            qr_file = Path("qrcode.txt")
                            qr_file.write_text(str(qr_data))
                            print(f"💾 Salvo em: {qr_file.absolute()}")
                            break
                    
                    # Imprime o evento completo para debug
                    print(json.dumps(data, indent=2)[:200])
                    print()
                    
                except asyncio.TimeoutError:
                    print("⏱️  Timeout aguardando evento...")
                    break
                    
    except Exception as e:
        print(f"❌ Erro na conexão WebSocket: {e}")
        print(f"\n💡 Dica: WebSocket pode estar em um endpoint diferente")
        print(f"   Tente também: ws://localhost:8080/")
        print(f"   ou verificar os logs do container:")
        print(f"   docker logs evolution_api | grep -i websocket")

if __name__ == "__main__":
    print("📱 Tentando obter QR code via WebSocket...\n")
    
    try:
        asyncio.run(connect_and_get_qrcode())
    except KeyboardInterrupt:
        print("\n⌚ Interrompido pelo usuário")
