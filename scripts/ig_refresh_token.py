#!/usr/bin/env python3
"""Renova o token de longa duração do Instagram antes que ele expire.

CLI equivalente ao job agendado `windmill/f/whatbot/refresh_ig_token.py` —
mesma lógica (`whatbot.instagram_credentials.refresh_long_lived_token`),
utilizável manualmente fora do Windmill.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests
from dotenv import load_dotenv

from whatbot.channels import INSTAGRAM, ChannelRouter, EvolutionApiClient
from whatbot.config import (
    DEFAULT_IG_TOKEN_LIFETIME_DAYS,
    ENV_DB_DSN,
    ENV_EVOLUTION_API_INSTANCE_NAME,
    ENV_EVOLUTION_API_KEY,
    is_placeholder,
    resolve_db_dsn,
    resolve_evolution_base_url,
)
from whatbot.db import Database
from whatbot.instagram_credentials import refresh_long_lived_token
from whatbot.instagram_health import check_credential_expiry


def _build_admin_router() -> ChannelRouter | None:
    """A bare WhatsApp router, just enough to send admin alerts (see
    `whatbot/channels/base.py::ADMIN_CHANNEL`) — this script never sends
    anything to a customer."""
    api_key = os.getenv(ENV_EVOLUTION_API_KEY)
    instance_name = os.getenv(ENV_EVOLUTION_API_INSTANCE_NAME)
    if is_placeholder(api_key) or is_placeholder(instance_name):
        return None
    return ChannelRouter(
        [
            EvolutionApiClient(
                api_key=api_key,
                instance_name=instance_name,
                base_url=resolve_evolution_base_url(),
            )
        ]
    )


def main() -> int:
    load_dotenv()

    dsn = resolve_db_dsn(os.getenv(ENV_DB_DSN))
    if is_placeholder(dsn):
        print("Erro: DB_DSN não configurado")
        return 1

    db = Database(dsn)
    db.ensure_schema()
    credential = db.get_channel_credential(INSTAGRAM)
    if credential is None:
        print("Nenhuma credencial do Instagram salva ainda (rode ig_oauth.py primeiro).")
        return 1

    try:
        refreshed = refresh_long_lived_token(credential.access_token)
    except requests.RequestException as exc:
        print(f"Erro renovando token: {exc}")
        if getattr(exc, "response", None) is not None:
            print(exc.response.text)
        return 1

    expires_in = refreshed.get("expires_in")
    if expires_in:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    else:
        # A renovação não teve erro, mas a resposta não trouxe `expires_in`.
        # Não reaproveitamos `credential.expires_at` (que pode já estar perto
        # de expirar — motivo de estarmos renovando) — isso geraria um
        # alerta falso de expiração logo após uma renovação bem-sucedida
        # (critic MENOR 6). Usa um default documentado em vez disso.
        print(
            "Aviso: resposta de renovação sem 'expires_in'; assumindo "
            f"{DEFAULT_IG_TOKEN_LIFETIME_DAYS} dias de validade."
        )
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=DEFAULT_IG_TOKEN_LIFETIME_DAYS
        )
    db.upsert_channel_credential(
        INSTAGRAM,
        refreshed.get("access_token", credential.access_token),
        account_id=credential.account_id,
        expires_at=expires_at,
    )
    print("Token renovado com sucesso.")
    if expires_at:
        print(f"Nova expiração: {expires_at.isoformat()}")

    router = _build_admin_router()
    if router is not None:
        check_credential_expiry(db, router, INSTAGRAM)

    return 0


if __name__ == "__main__":
    sys.exit(main())
