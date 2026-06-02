#!/usr/bin/env python3
"""Script para testar diferentes formas de autenticação na Evolution API."""

import requests
import json

BASE_URL = "http://localhost:8080"

# Teste 1: Sem autenticação
print("🔍 Teste 1: Sem autenticação...")
try:
    resp = requests.get(f"{BASE_URL}/instance/fetchInstances", timeout=5)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print("✅ Funciona sem autenticação!")
    else:
        print(f"Response: {resp.text[:200]}")
except Exception as e:
    print(f"❌ Erro: {e}")

# Teste 2: Com header "apikey"
print("\n🔍 Teste 2: Com header 'apikey'...")
try:
    resp = requests.get(
        f"{BASE_URL}/instance/fetchInstances",
        headers={"apikey": "change-me"},
        timeout=5
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print("✅ Funciona com apikey!")
        print(f"Response: {resp.json()}")
except Exception as e:
    print(f"❌ Erro: {e}")

# Teste 3: Com header "Authorization"
print("\n🔍 Teste 3: Com header 'Authorization: Bearer'...")
try:
    resp = requests.get(
        f"{BASE_URL}/instance/fetchInstances",
        headers={"Authorization": "Bearer change-me"},
        timeout=5
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print("✅ Funciona com Authorization!")
except Exception as e:
    print(f"❌ Erro: {e}")

# Teste 4: Com X-API-Key
print("\n🔍 Teste 4: Com header 'X-API-Key'...")
try:
    resp = requests.get(
        f"{BASE_URL}/instance/fetchInstances",
        headers={"X-API-Key": "change-me"},
        timeout=5
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print("✅ Funciona com X-API-Key!")
except Exception as e:
    print(f"❌ Erro: {e}")

# Teste 5: Health check
print("\n🔍 Teste 5: Health check na API...")
try:
    resp = requests.get(f"{BASE_URL}/health", timeout=5)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}")
except Exception as e:
    print(f"❌ Erro: {e}")
