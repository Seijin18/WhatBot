#!/usr/bin/env python3
"""Deleta e recria a instancia WhatsApp, aguardando o QR code."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests
from dotenv import load_dotenv

from whatbot.config import resolve_evolution_base_url

load_dotenv()

BASE_URL = resolve_evolution_base_url()
API_KEY = __import__("os").getenv("EVOLUTION_API_KEY", "change-me")
INSTANCE = __import__("os").getenv("EVOLUTION_API_INSTANCE_NAME", "bot_whatsapp")
HEADERS = {"apikey": API_KEY, "Content-Type": "application/json"}


def extract_qr_base64(payload: dict) -> str | None:
    if isinstance(payload.get("base64"), str) and payload["base64"]:
        return payload["base64"]
    qrcode = payload.get("qrcode")
    if isinstance(qrcode, dict) and qrcode.get("base64"):
        return qrcode["base64"]
    if isinstance(qrcode, str) and qrcode:
        return qrcode
    return None


def save_qr_html(instance_name: str, qr_base64: str) -> Path:
    html_file = Path("qrcode.html")
    html_file.write_text(
        f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>WhatBot QR</title></head>
<body style="font-family:Arial;text-align:center;padding:24px">
<h1 style="color:#25D366">Parear WhatsApp Business</h1>
<p>Instancia: <strong>{instance_name}</strong></p>
<img src="data:image/png;base64,{qr_base64}" alt="QR Code" style="max-width:420px">
<p>O QR expira em poucos minutos. Execute o script novamente se necessario.</p>
</body></html>""",
        encoding="utf-8",
    )
    return html_file


def main() -> int:
    print(f"Evolution API: {BASE_URL}")
    print(f"Instancia:     {INSTANCE}\n")

    print("1/4 Deletando instancia existente...")
    try:
        resp = requests.delete(
            f"{BASE_URL}/instance/delete/{INSTANCE}",
            headers=HEADERS,
            timeout=15,
        )
        print(f"     Status: {resp.status_code}")
    except requests.RequestException as exc:
        print(f"     Aviso: {exc}")

    time.sleep(3)

    print("2/4 Criando nova instancia...")
    try:
        resp = requests.post(
            f"{BASE_URL}/instance/create",
            headers=HEADERS,
            json={
                "instanceName": INSTANCE,
                "qrcode": True,
                "integration": "WHATSAPP-BAILEYS",
            },
            timeout=30,
        )
        resp.raise_for_status()
        create_result = resp.json()
        print(f"     Status: {resp.status_code}")
    except requests.RequestException as exc:
        print(f"     Erro: {exc}")
        if getattr(exc, "response", None) is not None:
            print(exc.response.text)
        return 1

    qr_base64 = extract_qr_base64(create_result)
    if qr_base64:
        html = save_qr_html(INSTANCE, qr_base64)
        print(f"\nQR code obtido na criacao. Abra: {html.resolve()}")
        return 0

    print("3/4 Aguardando QR code (ate 60s)...")
    for attempt in range(1, 21):
        try:
            resp = requests.get(
                f"{BASE_URL}/instance/connect/{INSTANCE}",
                headers={"apikey": API_KEY},
                timeout=20,
            )
            if resp.status_code == 200:
                result = resp.json()
                qr_base64 = extract_qr_base64(result)
                if qr_base64:
                    html = save_qr_html(INSTANCE, qr_base64)
                    print(f"\n4/4 QR code gerado na tentativa {attempt}. Abra: {html.resolve()}")
                    return 0
                print(f"     Tentativa {attempt}/20: {json.dumps(result)[:120]}")
            else:
                print(f"     Tentativa {attempt}/20: HTTP {resp.status_code}")
        except requests.RequestException as exc:
            print(f"     Tentativa {attempt}/20: {exc}")
        time.sleep(3)

    print("\nQR code nao gerado. Verifique os logs:")
    print("  docker logs evolution_api --tail 50")
    print("\nResposta da criacao:")
    print(json.dumps(create_result, indent=2, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    sys.exit(main())
