#!/usr/bin/env python3
"""Inscreve a conta do Instagram para receber webhooks de `messages`.

`POST https://graph.instagram.com/v23.0/me/subscribed_apps?subscribed_fields=messages`
— sem isso, a conta nunca entrega eventos para `whatbot/ingress.py`, mesmo
com o endpoint publicamente acessível e o token válido.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests
from dotenv import load_dotenv

from whatbot.channels import INSTAGRAM
from whatbot.config import ENV_DB_DSN, is_placeholder, resolve_db_dsn
from whatbot.db import Database
from whatbot.instagram_credentials import subscribe_webhook


def main() -> int:
    load_dotenv()

    dsn = resolve_db_dsn(os.getenv(ENV_DB_DSN))
    access_token = os.getenv("IG_ACCESS_TOKEN")
    if not access_token and not is_placeholder(dsn):
        db = Database(dsn)
        db.ensure_schema()
        credential = db.get_channel_credential(INSTAGRAM)
        access_token = credential.access_token if credential else None

    if not access_token:
        print("Erro: nenhum access_token disponível (IG_ACCESS_TOKEN ou canal_credenciais)")
        return 1

    try:
        result = subscribe_webhook(access_token)
    except requests.RequestException as exc:
        print(f"Erro inscrevendo webhook: {exc}")
        if getattr(exc, "response", None) is not None:
            print(exc.response.text)
        return 1

    print("Inscrição concluída:")
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
