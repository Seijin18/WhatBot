#requirements:
#psycopg[binary]
#psycopg_pool
#requests
#google-genai
#python-dotenv

from typing import Any, Dict


def main() -> Dict[str, Any]:
    """Job agendado: renova o token de longa duração do Instagram antes que
    expire, e alerta o admin se estiver perto de expirar mesmo assim.

    Requirement "Renovação automática de credencial"
    (`openspec/changes/instagram-ingestion-service/specs/instagram/spec.md`).
    Mesma lógica de `scripts/ig_refresh_token.py`, publicada como job
    agendado (ver tasks.md 3.3) — mantém um único lugar
    (`whatbot/instagram_credentials.py`) com as chamadas HTTP.
    """
    import sys
    from datetime import datetime, timedelta, timezone

    if "/whatbot" not in sys.path:
        sys.path.insert(0, "/whatbot")

    import os

    import requests

    from whatbot.channels import INSTAGRAM, ChannelRouter, EvolutionApiClient
    from whatbot.config import (
        DEFAULT_IG_TOKEN_LIFETIME_DAYS,
        ENV_DB_DSN,
        ENV_EVOLUTION_API_INSTANCE_NAME,
        ENV_EVOLUTION_API_KEY,
        bootstrap_env,
        is_placeholder,
        resolve_db_dsn,
        resolve_evolution_base_url,
    )
    from whatbot.db import Database
    from whatbot.instagram_credentials import refresh_long_lived_token
    from whatbot.instagram_health import check_credential_expiry

    bootstrap_env()

    dsn = resolve_db_dsn(os.getenv(ENV_DB_DSN))
    if is_placeholder(dsn):
        return {"ok": False, "error": "db_not_configured"}

    db = Database(dsn)
    db.ensure_schema()
    credential = db.get_channel_credential(INSTAGRAM)
    if credential is None:
        return {"ok": True, "skipped": True, "reason": "no_credential_configured"}

    api_key = os.getenv(ENV_EVOLUTION_API_KEY)
    instance_name = os.getenv(ENV_EVOLUTION_API_INSTANCE_NAME)
    router = None
    if not is_placeholder(api_key) and not is_placeholder(instance_name):
        router = ChannelRouter(
            [
                EvolutionApiClient(
                    api_key=api_key,
                    instance_name=instance_name,
                    base_url=resolve_evolution_base_url(),
                )
            ]
        )

    try:
        refreshed = refresh_long_lived_token(credential.access_token)
    except requests.RequestException as exc:
        detail = str(exc)
        if router is not None:
            from whatbot.channels.router import send_admin
            from whatbot.config import get_admin_phones

            for admin_phone in get_admin_phones():
                send_admin(
                    router,
                    admin_phone,
                    f"⚠️ *Instagram*: falha ao renovar o token de acesso: {detail}",
                )
        return {"ok": False, "error": "refresh_failed", "detail": detail}

    expires_in = refreshed.get("expires_in")
    if expires_in:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    else:
        # Renovação sem erro, mas sem `expires_in` na resposta: não reaproveita
        # `credential.expires_at` (que pode já estar perto de expirar — motivo
        # de estarmos renovando), senão o alerta de expiração dispara mesmo
        # após uma renovação bem-sucedida (critic MENOR 6).
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=DEFAULT_IG_TOKEN_LIFETIME_DAYS
        )
    db.upsert_channel_credential(
        INSTAGRAM,
        refreshed.get("access_token", credential.access_token),
        account_id=credential.account_id,
        expires_at=expires_at,
    )

    alerted = False
    if router is not None:
        alerted = check_credential_expiry(db, router, INSTAGRAM)

    return {
        "ok": True,
        "refreshed": True,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "alerted": alerted,
    }
