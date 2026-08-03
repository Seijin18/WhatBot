#!/usr/bin/env python3
"""Assina e envia um payload de webhook do Instagram para teste local.

Não depende da Meta: monta um payload no formato real
(`whatbot/instagram_webhook.py`), assina com `IG_APP_SECRET`
(`X-Hub-Signature-256`, o mesmo HMAC-SHA256 que `whatbot/ingress.py` valida)
e faz o POST contra um serviço de ingestão rodando localmente — cobre o
caminho ponta a ponta (assinatura -> confirmação -> processamento em
background -> resposta ao cliente) sem esperar um evento real chegar.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests
from dotenv import load_dotenv


def build_payload(sender_id: str, page_id: str, text: str, message_id: str) -> dict:
    return {
        "object": "instagram",
        "entry": [
            {
                "id": page_id,
                "time": int(time.time()),
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": page_id},
                        "timestamp": int(time.time()),
                        "message": {"mid": message_id, "text": text},
                    }
                ],
            }
        ],
    }


def sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Simula um webhook do Instagram")
    parser.add_argument(
        "--url", default=os.getenv("IG_INGRESS_URL", "http://localhost:8090/webhook/instagram")
    )
    parser.add_argument("--secret", default=os.getenv("IG_APP_SECRET"))
    parser.add_argument("--sender", default="17841400000000001", help="IGSID do cliente simulado")
    parser.add_argument("--page-id", default="17841400000000000")
    parser.add_argument("--text", default="Olá, vocês têm yoga?")
    parser.add_argument("--message-id", default=f"sim-{int(time.time())}")
    args = parser.parse_args()

    if not args.secret:
        print("Erro: informe --secret ou configure IG_APP_SECRET")
        return 1

    payload = build_payload(args.sender, args.page_id, args.text, args.message_id)
    body = json.dumps(payload).encode("utf-8")
    signature = sign(body, args.secret)

    print(f"POST {args.url}")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    try:
        response = requests.post(
            args.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"Erro chamando o serviço de ingestão: {exc}")
        return 1

    print(f"Status: {response.status_code}")
    print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    sys.exit(main())
