"""Health alerts for the Instagram integration.

Requirement "Alertas de saúde da integração"
(`openspec/changes/instagram-ingestion-service/specs/instagram/spec.md`):

- `IG_ALERT_FAIL_STREAK` consecutive outbound send failures -> alert.
- `IG_ALERT_SILENCE_MINUTES` without an inbound webhook event -> alert.
- Credential within `IG_CREDENTIAL_EXPIRY_WARNING_DAYS` of expiring -> alert.

All three reuse `whatbot/channels/router.py::send_admin` (never hold a
concrete channel client here, per `openspec/project.md` "Camadas") and are
driven by `whatbot/queue.py::run_periodic_queue_checks` (webhook silence,
credential expiry) or by `whatbot/main.py::process_customer_message()` around
the real outbound send (consecutive failures) — see `record_send_result`,
which persists the streak in Postgres (`canal_envio_falhas`) so it survives
across Windmill executions. `SendFailureMonitor` is kept as a simpler
in-memory helper covered directly by `tests/test_instagram_health.py`, but is
not itself wired to the send path — `record_send_result` is.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .channels import INSTAGRAM, channel_label
from .channels.router import send_admin
from .config import (
    IG_CREDENTIAL_EXPIRY_WARNING_DAYS,
    get_admin_phones,
    ig_alert_fail_streak,
    ig_alert_silence_minutes,
)

logger = logging.getLogger("whatbot.instagram_health")


class SendFailureMonitor:
    """Tracks consecutive send failures for one channel, in-process.

    A success anywhere in the sequence resets the streak (Requirement
    scenario "Sequência de falhas de envio atinge o limiar": "um envio
    bem-sucedido no meio da sequência zera a contagem"). `record_failure()`
    returns `True` exactly on the call where the streak first reaches the
    threshold, so a caller alerts once instead of on every failure after
    that point.
    """

    def __init__(self, canal: str = INSTAGRAM, *, threshold: int | None = None):
        self.canal = canal
        self._threshold = threshold
        self._streak = 0

    @property
    def threshold(self) -> int:
        return self._threshold if self._threshold is not None else ig_alert_fail_streak()

    @property
    def streak(self) -> int:
        return self._streak

    def record_success(self) -> None:
        self._streak = 0

    def record_failure(self) -> bool:
        self._streak += 1
        return self._streak >= self.threshold and self._streak == self.threshold


def record_send_result(db: Any, router: Any, canal: str, *, success: bool) -> bool:
    """Persisted counterpart of `SendFailureMonitor`, wired to the real send path.

    Called from `whatbot/main.py::process_customer_message()` around the
    actual outbound send for `canal` (critic BLOQUEADOR 1: `SendFailureMonitor`
    had a test in isolation but nothing in the real send path ever called
    `record_failure`/`record_success`, so the alert never fired in
    production; on top of that, an in-process counter would not survive
    across Windmill executions, which each run in a fresh process). The
    streak itself lives in Postgres (`Database.increment_send_fail_streak` /
    `reset_send_fail_streak`), not in this function's call stack, so it does
    survive.

    Best-effort: a failure to read/write the streak (e.g. DB hiccup) is
    logged and swallowed — it must never turn a customer-facing send
    success/failure into an unrelated 500, and it must never block the
    caller from returning its own result.

    Returns whether an alert was sent (only possible on `success=False`,
    exactly on the delivery where the streak first reaches
    `IG_ALERT_FAIL_STREAK` — matches the "zera a contagem" / "dispara uma
    vez" semantics `tests/test_instagram_health.py` already covers for
    `SendFailureMonitor`).
    """
    try:
        if success:
            db.reset_send_fail_streak(canal)
            return False
        streak = db.increment_send_fail_streak(canal)
    except Exception:
        logger.exception(
            "Falha ao persistir streak de envio para %s; alerta pode não disparar", canal
        )
        return False
    threshold = ig_alert_fail_streak()
    if streak >= threshold and streak == threshold:
        return alert_fail_streak(router, canal, streak)
    return False


def alert_fail_streak(router: Any, canal: str, streak: int) -> bool:
    """Notify every admin about a consecutive-failure streak on `canal`."""
    admins = get_admin_phones()
    text = (
        f"⚠️ *{channel_label(canal)}*: {streak} envios consecutivos falharam. "
        "Verifique a credencial e a integração."
    )
    sent = False
    for admin_phone in admins:
        send_admin(router, admin_phone, text)
        sent = True
    return sent


def alert_credential_expiring(router: Any, canal: str, expires_at: datetime) -> bool:
    admins = get_admin_phones()
    text = (
        f"⚠️ *{channel_label(canal)}*: a credencial de acesso expira em "
        f"{expires_at.isoformat()}. Renove antes que a integração pare de funcionar."
    )
    sent = False
    for admin_phone in admins:
        send_admin(router, admin_phone, text)
        sent = True
    return sent


def alert_webhook_silence(router: Any, canal: str, minutes: float) -> bool:
    admins = get_admin_phones()
    text = (
        f"⚠️ *{channel_label(canal)}*: nenhum evento de webhook recebido há "
        f"{int(minutes)} minutos. Verifique a assinatura do webhook e a exposição HTTPS."
    )
    sent = False
    for admin_phone in admins:
        send_admin(router, admin_phone, text)
        sent = True
    return sent


def check_credential_expiry(
    db: Any, router: Any, canal: str = INSTAGRAM, *, now: datetime | None = None
) -> bool:
    """Alert if `canal`'s credential is within the expiry warning window.

    No alert (and no error) if there is no credential on record yet — an
    integration that was never configured is not this alert's job to flag
    (Requirement scenario "Credencial perto de expirar" only applies once a
    credential exists).
    """
    now = now or datetime.now(timezone.utc)
    credential = db.get_channel_credential(canal)
    if credential is None or credential.expires_at is None:
        return False
    remaining = credential.expires_at - now
    if remaining > timedelta(days=IG_CREDENTIAL_EXPIRY_WARNING_DAYS):
        return False
    return alert_credential_expiring(router, canal, credential.expires_at)


def check_webhook_silence(
    db: Any, router: Any, canal: str = INSTAGRAM, *, now: datetime | None = None
) -> bool:
    """Alert if no `canal` webhook event has been recorded recently enough.

    No alert if no event was ever recorded — indistinguishable from "never
    configured", which is not this alert's concern (see design.md, non-goals).
    """
    now = now or datetime.now(timezone.utc)
    last_at = db.get_last_webhook_event_at(canal)
    if last_at is None:
        return False
    threshold = timedelta(minutes=ig_alert_silence_minutes())
    elapsed = now - last_at
    if elapsed < threshold:
        return False
    return alert_webhook_silence(router, canal, elapsed.total_seconds() / 60)


def run_instagram_health_checks(db: Any, router: Any, *, now: datetime | None = None) -> dict:
    """Run every periodic Instagram health check; called from
    `whatbot/queue.py::run_periodic_queue_checks` (task 2.2/3.4 share the
    same scheduled job, no new Windmill job needed just for these)."""
    return {
        "credential_expiry_alerted": check_credential_expiry(db, router, now=now),
        "webhook_silence_alerted": check_webhook_silence(db, router, now=now),
    }
