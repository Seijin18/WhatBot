#!/usr/bin/env python3
"""Registra webhook Evolution apontando para o Windmill local."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whatbot.config import resolve_evolution_base_url

load_dotenv()


def setup_webhook(
    webhook_url: str,
    instance_name: str,
    api_key: str,
    base_url: str = "http://localhost:8080",
    auth_header: str | None = None,
) -> dict:
    url = f"{base_url.rstrip('/')}/webhook/set/{instance_name}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
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


WORKSPACE = os.getenv("WINDMILL_WORKSPACE", "admins")
SCRIPT_PATH = os.getenv("WINDMILL_SCRIPT_PATH", "f/whatbot/handler")
WINDMILL_INTERNAL = os.getenv(
    "WINDMILL_WEBHOOK_URL",
    f"http://windmill-server:8000/api/w/{WORKSPACE}/webhooks/webhook/{SCRIPT_PATH}",
)


def main() -> int:
    webhook_url = WINDMILL_INTERNAL
    instance = os.getenv("EVOLUTION_API_INSTANCE_NAME", "bot_whatsapp")
    api_key = os.getenv("EVOLUTION_API_KEY", "change-me")
    base_url = resolve_evolution_base_url()

    print("Configurando webhook Evolution -> Windmill")
    print(f"  Instancia:  {instance}")
    print(f"  Evolution:  {base_url}")
    print(f"  Windmill:   {webhook_url}")
    print()
    print("Certifique-se de que o script f/whatbot/handler existe no Windmill")
    print("e que o webhook esta habilitado no script (aba Webhook).")
    print()

    try:
        result = setup_webhook(
            webhook_url=webhook_url,
            instance_name=instance,
            api_key=api_key,
            base_url=base_url,
        )
    except Exception as exc:
        print(f"Erro: {exc}")
        return 1

    import json

    print("Webhook registrado:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
