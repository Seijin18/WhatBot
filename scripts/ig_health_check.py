#!/usr/bin/env python3
"""Verifica a saúde da integração com o Instagram: token, expiração,
inscrição do webhook e último evento recebido.

Espelha `scripts/health_check.py` (WhatsApp/Evolution), mas focado no que é
específico do Instagram — as checagens de saúde recorrentes já rodam
automaticamente via `whatbot/instagram_health.py` dentro do job agendado
(`run_periodic_queue_checks`); este script é a versão sob demanda, para
diagnóstico manual.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests
from dotenv import load_dotenv

from whatbot.channels import INSTAGRAM
from whatbot.config import (
    ENV_DB_DSN,
    ig_alert_silence_minutes,
    is_placeholder,
    resolve_db_dsn,
)
from whatbot.db import Database
from whatbot.instagram_credentials import get_account_info, get_subscribed_apps


def main() -> int:
    load_dotenv()
    ok = True

    dsn = resolve_db_dsn(os.getenv(ENV_DB_DSN))
    if is_placeholder(dsn):
        print("❌ DB_DSN não configurado")
        return 1

    db = Database(dsn)
    db.ensure_schema()

    credential = db.get_channel_credential(INSTAGRAM)
    if credential is None:
        print("❌ Nenhuma credencial do Instagram salva (rode scripts/ig_oauth.py)")
        return 1

    print(f"✔️  Credencial encontrada (account_id={credential.account_id})")
    if credential.expires_at:
        now = datetime.now(timezone.utc)
        remaining = credential.expires_at - now
        if remaining.total_seconds() < 0:
            print(f"❌ Token expirado em {credential.expires_at.isoformat()}")
            ok = False
        elif remaining.days < 7:
            print(f"⚠️  Token expira em {remaining.days} dia(s) ({credential.expires_at.isoformat()})")
        else:
            print(f"✔️  Token válido por mais {remaining.days} dia(s)")
    else:
        print("⚠️  Sem data de expiração registrada")

    try:
        info = get_account_info(credential.access_token)
        print(f"✔️  Token aceito pela API: @{info.get('username')} (id={info.get('id')})")
    except requests.RequestException as exc:
        print(f"❌ Token rejeitado pela API: {exc}")
        ok = False

    try:
        subs = get_subscribed_apps(credential.access_token)
        subscribed = bool(subs.get("data"))
        print(f"{'✔️ ' if subscribed else '❌'} Inscrição de webhook: {subs}")
        ok = ok and subscribed
    except requests.RequestException as exc:
        print(f"❌ Erro consultando inscrição: {exc}")
        ok = False

    last_event = db.get_last_webhook_event_at(INSTAGRAM)
    if last_event is None:
        print("⚠️  Nenhum evento de webhook recebido ainda")
    else:
        elapsed_minutes = (datetime.now(timezone.utc) - last_event).total_seconds() / 60
        threshold = ig_alert_silence_minutes()
        status = "✔️ " if elapsed_minutes < threshold else "⚠️ "
        print(f"{status}Último evento de webhook: {last_event.isoformat()} ({int(elapsed_minutes)} min atrás)")

    print("\nResultado geral:", "✅ saudável" if ok else "❌ com problemas")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
