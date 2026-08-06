"""Dedicated Meta webhook ingestion service (FastAPI) — Instagram and,
since `whatsapp-cloud-channel-client`, WhatsApp Cloud API.

See `openspec/changes/instagram-ingestion-service/design.md`, Decisão
"serviço FastAPI dedicado, não apontar o webhook direto para o Windmill":
this module only does the handshake, signature validation and immediate
confirmation; the actual processing — which still ends in
`whatbot.main.main(payload)`, no duplicated domain logic — runs in a
`BackgroundTasks` job *after* the HTTP response has already been returned.

Both Meta products share the exact same `hub.challenge`/`X-Hub-Signature-256`
protocol (`verify_handshake`/`verify_signature` below are product-agnostic,
parameterized by whichever verify-token/app-secret env vars the caller
passes) — only the payload parser and the route path differ per product.
See `openspec/changes/whatsapp-cloud-channel-client/design.md`, "Decisão:
reaproveitar `whatbot/ingress.py`, não duplicar o handshake Meta".

The WhatsApp/Evolution path (`WHATSAPP_PROVIDER=evolution`, the default)
remains unaffected: it keeps going straight through
`windmill/f/whatbot/handler.py` -> `whatbot.main.main()`, synchronously, not
through this service at all. This service is only used by Instagram and by
WhatsApp when `WHATSAPP_PROVIDER=cloud`, both of which the Meta platform
holds to a strict "acknowledge fast, otherwise we resend" contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from .channels import ChannelError, INSTAGRAM, WHATSAPP, send_to_contact
from .config import (
    ENV_IG_APP_SECRET,
    ENV_IG_WEBHOOK_VERIFY_TOKEN,
    ENV_WA_CLOUD_APP_SECRET,
    ENV_WA_CLOUD_WEBHOOK_VERIFY_TOKEN,
    bootstrap_env,
    get_admin_api_token,
)
from .instagram_webhook import KIND_MESSAGE, parse_instagram_payload
from .main import get_infra, main as whatbot_main
from .storage import StorageError, get_storage_backend
from .whatsapp_cloud_webhook import (
    KIND_MEDIA_ONLY as WA_KIND_MEDIA_ONLY,
    KIND_MESSAGE as WA_KIND_MESSAGE,
    parse_whatsapp_cloud_payload,
)

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


def _extract_whatsapp_message_events(body: bytes) -> List[Dict[str, Any]]:
    """Parse the raw body and keep customer-message and media events to process.

    `statuses` (delivery/read receipts) and malformed events are classified
    by `parse_whatsapp_cloud_payload` but have nothing for
    `whatbot.main.main()` to act on — see `whatbot/whatsapp_cloud_webhook.py`.
    Media-only events (`KIND_MEDIA_ONLY`) *are* forwarded since
    `conversation-history-media-storage`: previously they had no `data`
    at all; now `whatbot.main._dispatch_payload` downloads and persists
    them (see `_handle_media_message`).
    """
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        logger.warning("Corpo do webhook do WhatsApp Cloud não é JSON válido")
        return []
    events = parse_whatsapp_cloud_payload(payload)
    return [
        e["data"]
        for e in events
        if e["kind"] in (WA_KIND_MESSAGE, WA_KIND_MEDIA_ONLY) and e["data"]
    ]


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


@app.get("/webhook/whatsapp")
def verify_whatsapp_webhook(request: Request):
    """Handshake `GET` de verificação do webhook do WhatsApp Cloud API.

    Mesmo protocolo Meta que `verify_webhook` (Instagram) — só troca o env
    var do token esperado. Ver docstring do módulo.
    """
    params = request.query_params
    expected = os.getenv(ENV_WA_CLOUD_WEBHOOK_VERIFY_TOKEN)
    if verify_handshake(params.get("hub.mode"), params.get("hub.verify_token"), expected):
        return PlainTextResponse(params.get("hub.challenge", ""), status_code=200)
    return PlainTextResponse("verification failed", status_code=403)


@app.post("/webhook/whatsapp")
async def receive_whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recebe um POST do webhook do WhatsApp Cloud API: valida, confirma
    imediatamente, processa depois — mesmo formato de `receive_webhook`
    (Instagram), trocando a validação de assinatura e o parser do payload.
    """
    body = await request.body()
    secret = os.getenv(ENV_WA_CLOUD_APP_SECRET)
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(secret, body, signature):
        logger.warning("Webhook do WhatsApp Cloud recusado: assinatura inválida")
        return JSONResponse({"ok": False, "error": "invalid_signature"}, status_code=403)

    events = _extract_whatsapp_message_events(body)
    for event_payload in events:
        background_tasks.add_task(_process_event, event_payload)

    return JSONResponse({"ok": True, "queued": len(events)}, status_code=200)


def _check_admin_auth(authorization: str | None) -> None:
    """Bearer-token auth for `/admin/*` (Requirement "API administrativa
    exige autenticação", `message-history`).

    Deliberately simple (a single static token, no SSO/JWT) — see
    `design.md` Decisão 4: the only consumer is one internal backend
    (`camu-web-admin`, server-side). An unconfigured `ADMIN_API_TOKEN`
    fails closed (401), same criterion as `verify_handshake` above for the
    webhook token — never accept by omission.
    """
    expected = get_admin_api_token()
    if not expected:
        raise HTTPException(status_code=401, detail="ADMIN_API_TOKEN não configurado")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="token ausente")
    token = authorization.split(" ", 1)[1]
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="token inválido")


_ADMIN_UI_PATH = Path(__file__).parent / "static" / "admin_ui.html"


@app.get("/admin/ui")
def admin_ui() -> HTMLResponse:
    """Visualizador de conversas **temporário** (sem build, um único HTML
    servido pela mesma origem da API — evita configurar CORS).

    Autenticação acontece no próprio front-end: a página pede o
    `ADMIN_API_TOKEN` e guarda em `localStorage` do navegador, enviando-o
    como `Authorization: Bearer` em cada chamada às rotas `/admin/*`
    abaixo. Destinado a uso interno/local até o painel definitivo
    (`camu-web-admin`) assumir essa tela — não tem o cuidado de nunca expor
    o token ao browser que as demais integrações (`camu-web-admin`) devem
    ter, porque aqui o próprio browser É o cliente.
    """
    return HTMLResponse(_ADMIN_UI_PATH.read_text(encoding="utf-8"))


@app.get("/admin/conversas")
def list_conversas(authorization: str | None = Header(None)) -> Dict[str, Any]:
    """Lista contatos com última mensagem/preview (Requirement "Histórico
    paginado por conversa")."""
    _check_admin_auth(authorization)
    db, _router = get_infra()
    return {"ok": True, "conversas": db.list_conversations()}


@app.get("/admin/conversas/{contact_id}/mensagens")
def get_conversa_mensagens(
    contact_id: int,
    before: int | None = None,
    limit: int = 50,
    authorization: str | None = Header(None),
) -> Dict[str, Any]:
    """Histórico paginado por cursor de uma conversa (Requirement "Histórico
    paginado por conversa")."""
    _check_admin_auth(authorization)
    db, _router = get_infra()
    mensagens = db.get_conversation(contact_id, limit=limit, before=before)

    def _media_summary(media_id: int | None) -> Dict[str, Any] | None:
        # N+1 por página é aceitável aqui: uso só do admin, volume baixo
        # (não é o caminho de atendimento em tempo real).
        if media_id is None:
            return None
        media_file = db.get_media_file(media_id)
        if media_file is None:
            return None
        return {
            "id": media_file.id,
            "tipo": media_file.tipo,
            "mime_type": media_file.mime_type,
            "status": media_file.status,
        }

    return {
        "ok": True,
        "mensagens": [
            {
                "id": m.id,
                "direction": m.direction,
                "text": m.text,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "canal": m.canal,
                "message_id": m.message_id,
                "payload": m.payload,
                "media_id": m.media_id,
                "media": _media_summary(m.media_id),
            }
            for m in mensagens
        ],
    }


@app.get("/admin/midia/{media_id}")
def get_midia(media_id: int, authorization: str | None = Header(None)) -> Response:
    """Stream do binário de uma mídia salva (Requirement "Mídia recebida é
    baixada e referenciada" / "Armazenamento local isolado por chave") —
    nunca um path de disco exposto diretamente, sempre via `StorageBackend`.
    """
    _check_admin_auth(authorization)
    db, _router = get_infra()
    media_file = db.get_media_file(media_id)
    if media_file is None:
        raise HTTPException(status_code=404, detail="mídia não encontrada")
    try:
        data = get_storage_backend().open(media_file.storage_key)
    except StorageError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(
        content=data, media_type=media_file.mime_type or "application/octet-stream"
    )


@app.post("/admin/conversas/{contact_id}/mensagens")
async def enviar_mensagem_humana(
    contact_id: int, request: Request, authorization: str | None = Header(None)
) -> Dict[str, Any]:
    """Envio de mensagem como atendente humano (Requirement "Envio humano
    reusa o roteador de canais"): só aceito com o contato em atendimento
    humano (`ia_ativa=False`, mesmo critério de `whatbot/main.py` linha
    ~711), e sempre via `ChannelRouter`/`send_to_contact` — nunca um client
    de canal concreto.
    """
    _check_admin_auth(authorization)
    db, router = get_infra()
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="'text' é obrigatório")

    contact = db.get_contact_by_id(contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="contato não encontrado")
    if contact.ia_ativa:
        raise HTTPException(
            status_code=409, detail="contato não está em atendimento humano"
        )

    destino = contact.external_id or contact.phone
    try:
        result = send_to_contact(
            router,
            destino,
            text,
            canal=contact.canal,
            source="human_admin",
            contact_id=contact.id,
            human_agent=True,
        )
    except ChannelError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    db.save_message(contact.id, direction="out", text=text, canal=contact.canal)
    return {"ok": True, "result": result}


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": "whatbot-ingress",
        "canais": [INSTAGRAM, WHATSAPP],
    }
