#!/usr/bin/env python3
"""Configura o webhook da Evolution API apontando para o Windmill."""

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


def setup_webhook(
    webhook_url: str,
    instance_name: str,
    api_key: str,
    base_url: str = "http://localhost:8080",
    auth_header: str | None = None,
) -> dict:
    url = f"{base_url.rstrip('/')}/webhook/set/{instance_name}"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
    }
    body: dict = {
        "webhook": {
            "enabled": True,
            "url": webhook_url,
            "webhookByEvents": False,
            "webhookBase64": False,
            "events": ["MESSAGES_UPSERT"],
        }
    }
    if auth_header:
        body["webhook"]["headers"] = {"Authorization": auth_header}

    response = requests.post(url, headers=headers, json=body, timeout=15)
    response.raise_for_status()
    return response.json()


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Configura webhook Evolution -> Windmill")
    parser.add_argument(
        "webhook_url",
        help="URL do webhook Windmill (ex: https://windmill.example.com/api/r/.../webhook/whatbot)",
    )
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
    parser.add_argument(
        "--auth-header",
        default=os.getenv("WINDMILL_WEBHOOK_AUTH"),
        help="Valor completo do header Authorization enviado ao Windmill",
    )
    args = parser.parse_args()
    args.base_url = resolve_evolution_base_url(args.base_url)

    print(f"Configurando webhook da instância '{args.instance}'...")
    print(f"  Evolution API: {args.base_url}")
    print(f"  Destino:       {args.webhook_url}")

    try:
        result = setup_webhook(
            webhook_url=args.webhook_url,
            instance_name=args.instance,
            api_key=args.api_key,
            base_url=args.base_url,
            auth_header=args.auth_header,
        )
    except requests.RequestException as exc:
        print(f"Erro configurando webhook: {exc}")
        if getattr(exc, "response", None) is not None:
            print(exc.response.text)
        return 1

    print("Webhook configurado com sucesso:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
