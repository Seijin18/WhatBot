#!/usr/bin/env python3
"""Gera QR code HTML para parear a instância WhatsApp."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests
from dotenv import load_dotenv

from whatbot.config import resolve_evolution_base_url


def connect_instance(base_url: str, api_key: str, instance_name: str) -> dict:
    url = f"{base_url.rstrip('/')}/instance/connect/{instance_name}"
    response = requests.get(url, headers={"apikey": api_key}, timeout=20)
    response.raise_for_status()
    return response.json()


def save_qr_html(instance_name: str, qr_base64: str) -> Path:
    html_file = Path("qrcode.html")
    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>WhatBot - QR Code</title>
  <style>
    body {{ font-family: Arial, sans-serif; text-align: center; padding: 24px; }}
    h1 {{ color: #25D366; }}
    img {{ max-width: 420px; margin: 24px 0; }}
    .info {{ background: #f5f5f5; padding: 16px; border-radius: 8px; max-width: 520px; margin: 0 auto; }}
  </style>
</head>
<body>
  <h1>Parear WhatsApp Business</h1>
  <div class="info">
    <p><strong>Instância:</strong> {instance_name}</p>
    <p>Abra o WhatsApp Business no celular &gt; Dispositivos conectados &gt; Conectar dispositivo</p>
  </div>
  <img src="data:image/png;base64,{qr_base64}" alt="QR Code">
  <div class="info">
    <p>O QR code expira em poucos minutos. Se expirar, execute este script novamente.</p>
  </div>
</body>
</html>"""
    html_file.write_text(html_content, encoding="utf-8")
    return html_file


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Conecta instância e gera qrcode.html")
    parser.add_argument(
        "--instance",
        default=os.getenv("EVOLUTION_API_INSTANCE_NAME", "bot_whatsapp"),
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("EVOLUTION_API_KEY", "change-me"),
    )
    parser.add_argument(
        "--base-url",
        default=resolve_evolution_base_url(),
    )
    args = parser.parse_args()
    args.base_url = resolve_evolution_base_url(args.base_url)

    print(f"Conectando instância '{args.instance}'...")
    print(f"  Evolution API: {args.base_url}")
    try:
        result = connect_instance(args.base_url, args.api_key, args.instance)
    except requests.RequestException as exc:
        print(f"Erro ao conectar instância: {exc}")
        if getattr(exc, "response", None) is not None:
            print(exc.response.text)
        return 1

    qr_base64 = None
    if isinstance(result.get("base64"), str):
        qr_base64 = result["base64"]
    elif isinstance(result.get("qrcode"), dict):
        qr_base64 = result["qrcode"].get("base64")
    elif isinstance(result.get("qrcode"), str):
        qr_base64 = result["qrcode"]

    if not qr_base64:
        print("Resposta recebida, mas sem QR code. Detalhes:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("\nSe a instância já estiver conectada, verifique com:")
        print(f'curl -H "apikey: {args.api_key}" {args.base_url}/instance/fetchInstances')
        return 1

    html_file = save_qr_html(args.instance, qr_base64)
    print(f"QR code salvo em: {html_file.resolve()}")
    print("Abra qrcode.html no navegador e escaneie com o WhatsApp Business.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
