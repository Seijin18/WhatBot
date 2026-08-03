"""Dedicated Instagram webhook ingestion service (FastAPI).

See `openspec/changes/instagram-ingestion-service/design.md`, Decisão
"serviço FastAPI dedicado, não apontar o webhook direto para o Windmill":
this module only does the handshake, signature validation and immediate
confirmation; the actual processing — which still ends in
`whatbot.main.main(payload)`, no duplicated domain logic — runs in a
`BackgroundTasks` job *after* the HTTP response has already been returned.

The WhatsApp/Evolution path is unaffected: it keeps going straight through
`windmill/f/whatbot/handler.py` -> `whatbot.main.main()`, synchronously. This
module exists only for the Instagram side, which the Meta platform holds to a
strict "acknowledge fast, otherwise we resend" contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, List

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .channels import INSTAGRAM
from .config import ENV_IG_APP_SECRET, ENV_IG_WEBHOOK_VERIFY_TOKEN, bootstrap_env
from .instagram_webhook import KIND_MESSAGE, parse_instagram_payload
from .main import main as whatbot_main

logger = logging.getLogger("whatbot.ingress")

app = FastAPI(title="WhatBot — Instagram ingestion")


@app.on_event("startup")
def _startup() -> None:
    """Load `.env` once per process, not once per request.

    `bootstrap_env()` resolves Docker service hostnames (see
    `whatbot/config.py`), which does a real DNS lookup — cheap once at
    startup, expensive (and pointless to repeat) on every webhook delivery.
    """
    bootstrap_env()


def verify_handshake(mode: str | None, token: str | None, expected_token: str | None) -> bool:
    """`GET` verification handshake Meta performs when a webhook is registered.

    Requirement "Autenticidade e velocidade da ingestão": responds *only*
    with the configured token — never with a default/empty token, which
    would make an unconfigured deployment accept anything.
    """
    if not expected_token or not mode or not token:
        return False
    if mode != "subscribe":
        return False
    try:
        return hmac.compare_digest(token, expected_token)
    except (TypeError, UnicodeError):
        # Starlette decodes headers/query params as latin-1, so any byte
        # above 0x7F arrives as a non-ASCII `str`; `hmac.compare_digest`
        # raises `TypeError` on that instead of just returning `False`.
        # A malformed/hostile request must be refused (403), never crash
        # the endpoint with an unhandled 500 (critic BLOQUEADOR 3).
        return False


def verify_signature(secret: str | None, body: bytes, signature_header: str | None) -> bool:
    """Constant-time HMAC-SHA256 check over the *raw* request body.

    `signature_header` is Meta's `X-Hub-Signature-256` value, shaped
    `sha256=<hex digest>`. Deliberately compares over `body` (bytes captured
    before any JSON parsing) — see design.md: reserializing the parsed JSON
    can change byte-for-byte content (key order, spacing) and invalidate an
    otherwise legitimate signature. Uses `hmac.compare_digest`, not `==`, to
    avoid leaking timing information about the shared secret.
    """
    if not secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    provided = signature_header.split("=", 1)[1]
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(expected, provided)
    except (TypeError, UnicodeError):
        # Same non-ASCII header issue as `verify_handshake` above: a
        # malformed `X-Hub-Signature-256` (bytes >0x7F, arriving as a
        # non-ASCII `str` via Starlette's latin-1 header decoding) must be
        # refused (403), never propagate as an unhandled 500
        # (critic BLOQUEADOR 3).
        return False


def _process_event(payload: Dict[str, Any]) -> None:
    """Runs the real processing — off the webhook's response cycle.

    Delegates entirely to `whatbot.main.main()`, which already owns
    idempotency (`Database.record_webhook_event`, see `whatbot/main.py`) and
    every other step of the domain flow (contact resolution, LLM call,
    outbound send). No business logic is duplicated here.
    """
    try:
        whatbot_main(payload)
    except Exception:
        logger.exception("Erro processando evento do Instagram em background")


def _extract_message_events(body: bytes) -> List[Dict[str, Any]]:
    """Parse the raw body and keep only customer-message events to process.

    Echoes, story mentions, deleted-message notices and malformed events are
    classified by `parse_instagram_payload` but have nothing for
    `whatbot.main.main()` to act on today — see
    `whatbot/instagram_webhook.py`.
    """
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        logger.warning("Corpo do webhook do Instagram não é JSON válido")
        return []
    events = parse_instagram_payload(payload)
    return [e["data"] for e in events if e["kind"] == KIND_MESSAGE and e["data"]]


@app.get("/webhook/instagram")
def verify_webhook(request: Request):
    """Handshake `GET` de verificação do webhook (Requirement "Autenticidade
    e velocidade da ingestão")."""
    params = request.query_params
    expected = os.getenv(ENV_IG_WEBHOOK_VERIFY_TOKEN)
    if verify_handshake(params.get("hub.mode"), params.get("hub.verify_token"), expected):
        return PlainTextResponse(params.get("hub.challenge", ""), status_code=200)
    return PlainTextResponse("verification failed", status_code=403)


@app.post("/webhook/instagram")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receives a webhook POST: validate, confirm immediately, process later.

    Requirement "Autenticidade e velocidade da ingestão": an invalid
    signature is recused and *nothing* is processed. A valid one gets an
    immediate 200 while the actual processing (which may call the LLM) is
    scheduled via `BackgroundTasks` — Starlette only runs those after this
    response has already been handed back to the ASGI server, never before
    (see `tests/test_ingress.py` for the order-of-execution proof).
    """
    body = await request.body()
    secret = os.getenv(ENV_IG_APP_SECRET)
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(secret, body, signature):
        logger.warning("Webhook do Instagram recusado: assinatura inválida")
        return JSONResponse({"ok": False, "error": "invalid_signature"}, status_code=403)

    events = _extract_message_events(body)
    for event_payload in events:
        background_tasks.add_task(_process_event, event_payload)

    return JSONResponse({"ok": True, "queued": len(events)}, status_code=200)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "whatbot-ingress", "canal": INSTAGRAM}
