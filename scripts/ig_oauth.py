#!/usr/bin/env python3
"""Autoriza a conta do Instagram e troca o código por um token de longa duração.

Fluxo (ver `docs/INSTAGRAM_INTEGRATION_PLAN.md`, seção 3 "Token"):
1. `--print-url` imprime a URL de autorização; o admin abre no navegador,
   loga na conta profissional do Instagram e autoriza o app.
2. A Meta redireciona para `--redirect-uri` com `?code=...` na URL.
3. `--code <code>` troca o código por um token curto, depois por um token
   longo (~60 dias) e salva em `canal_credenciais` via `whatbot/db.py`.
"""

from __future__ import annotations

import argparse
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
from whatbot.instagram_credentials import (
    authorize_url,
    exchange_code_for_short_token,
    exchange_for_long_lived_token,
    get_account_info,
)


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Autoriza a conta do Instagram")
    parser.add_argument("--client-id", default=os.getenv("IG_APP_ID"))
    parser.add_argument("--client-secret", default=os.getenv("IG_CLIENT_SECRET"))
    parser.add_argument("--redirect-uri", default=os.getenv("IG_OAUTH_REDIRECT_URI"))
    parser.add_argument("--print-url", action="store_true", help="Só imprime a URL de autorização")
    parser.add_argument("--code", help="Código recebido no redirect após autorizar")
    args = parser.parse_args()

    if not args.client_id or not args.redirect_uri:
        print("Erro: informe --client-id/IG_APP_ID e --redirect-uri/IG_OAUTH_REDIRECT_URI")
        return 1

    if args.print_url or not args.code:
        url = authorize_url(args.client_id, args.redirect_uri)
        print("Abra esta URL, autorize a conta e copie o `code` do redirect:")
        print(url)
        return 0

    if not args.client_secret:
        print("Erro: informe --client-secret/IG_CLIENT_SECRET para trocar o código")
        return 1

    try:
        short = exchange_code_for_short_token(
            args.client_id, args.client_secret, args.redirect_uri, args.code
        )
        long_lived = exchange_for_long_lived_token(
            short["access_token"], args.client_secret
        )
        info = get_account_info(long_lived["access_token"])
    except requests.RequestException as exc:
        print(f"Erro trocando token: {exc}")
        if getattr(exc, "response", None) is not None:
            print(exc.response.text)
        return 1

    dsn = resolve_db_dsn(os.getenv(ENV_DB_DSN))
    if is_placeholder(dsn):
        print("DB_DSN não configurado — token obtido, mas não foi salvo:")
        print(long_lived)
        return 0

    expires_in = long_lived.get("expires_in")
    expires_at = None
    if expires_in:
        from datetime import datetime, timedelta, timezone

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    db = Database(dsn)
    db.ensure_schema()
    db.upsert_channel_credential(
        INSTAGRAM,
        long_lived["access_token"],
        account_id=str(info.get("id")) if info.get("id") else None,
        expires_at=expires_at,
    )
    print(f"Credencial salva para @{info.get('username')} (id={info.get('id')}).")
    if expires_at:
        print(f"Expira em: {expires_at.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
