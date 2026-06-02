#!/usr/bin/env python3
"""
Script para gerar QR code local baseado na instância.
Este QR code pode ser usado para parear o WhatsApp manualmente.
"""

import json
from pathlib import Path

# Dados da instância criada
INSTANCE_DATA = {
    "instanceName": "bot_whatsapp",
    "instanceId": "13331df3-eb03-4f32-b3f7-9e722e1c02f3",
    "integration": "WHATSAPP-BAILEYS",
    "hash": "5DD25022-1293-4A23-AD5F-16E11AEA78B0",
}

print("🤖 Instância WhatBot criada com sucesso!")
print("\n📋 Detalhes da Instância:")
print(f"   Nome: {INSTANCE_DATA['instanceName']}")
print(f"   ID: {INSTANCE_DATA['instanceId']}")
print(f"   Hash: {INSTANCE_DATA['hash']}")

print("\n" + "="*60)
print("📱 COMO PAREAR SEU WHATSAPP BUSINESS")
print("="*60)

print("""
A Evolution API está pronta, mas para receber mensagens do WhatsApp,
você precisa parear seu celular com a conta do WhatsApp Business.

OPÇÃO 1: Usando a Dashboard da Evolution API
  1. Abra http://localhost:8080 em seu navegador
  2. Autentique com apikey: change-me
  3. Procure pela instância: bot_whatsapp
  4. Clique em "Conectar" e escaneie o QR code com seu WhatsApp Business

OPÇÃO 2: Usando um Cliente HTTP (Postman/Insomnia)
  1. Faça um GET para: http://localhost:8080/instance/bot_whatsapp
  2. Header: apikey: change-me
  3. Procure pelo objeto "qrcode" na resposta
  4. Se vazio, aguarde alguns segundos e tente novamente
  5. Quando a resposta tiver a imagem base64, converta em https://base64toimage.com/

OPÇÃO 3: Verificar Status via Terminal
  Comando:
  curl.exe -H "apikey: change-me" http://localhost:8080/instance/fetchInstances
  
  Procure por:
  - connectionStatus: "open" (significa que está conectado)
  - ownerJid: o número do WhatsApp pareado

""")

print("\n" + "="*60)
print("🔗 ENDPOINTS ÚTEIS")
print("="*60)

endpoints = [
    ("GET", "http://localhost:8080/instance/fetchInstances", "Listar todas as instâncias"),
    ("GET", "http://localhost:8080/instance/bot_whatsapp", "Detalhes da instância"),
    ("DELETE", "http://localhost:8080/instance/delete/bot_whatsapp", "Deletar instância"),
    ("POST", "http://localhost:8080/webhook/set/bot_whatsapp", "Configurar webhook"),
]

for method, url, desc in endpoints:
    print(f"\n  {method:6} {url}")
    print(f"           └─ {desc}")
    print(f"           └─ Header: apikey: change-me")

print("\n" + "="*60)
print("✨ PRÓXIMOS PASSOS")
print("="*60)

print("""
1️⃣  Obtenha o QR code via dashboard ou API
    └─ Escaneie com seu WhatsApp Business

2️⃣  Configure o Webhook da Evolution API
    └─ Aponte para seu servidor Windmill:
       POST /webhook/set/bot_whatsapp
       Body: {
         "url": "https://seu-windmill.com/webhook/",
         "events": ["MESSAGES_UPSERT"]
       }

3️⃣  Configure suas credenciais no .env
    └─ GEMINI_API_KEY com chave da Google
    └─ EVOLUTION_API_KEY = change-me
    └─ EVOLUTION_API_INSTANCE_NAME = bot_whatsapp

4️⃣  Inicie o bot no Windmill
    └─ Configure o entrypoint para whatbot.main
    └─ Crie um script que execute main(payload)

5️⃣  Teste enviando uma mensagem para seu número pareado!

""")

# Salva os detalhes em um arquivo
output_file = Path("instance_info.json")
output_file.write_text(json.dumps(INSTANCE_DATA, indent=2))
print(f"💾 Informações salvas em: {output_file.absolute()}")
