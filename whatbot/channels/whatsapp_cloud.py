"""WhatsApp Cloud API integration for outbound messages.

Uses Meta's official WhatsApp Business Cloud API (`graph.facebook.com`),
replacing the non-official Evolution API/Baileys integration
(`whatsapp_evolution.py`) as an alternative implementation of the *same*
canal `"whatsapp"` — see `openspec/changes/whatsapp-cloud-channel-client/`.

Registered instead of `EvolutionApiClient`, never alongside it: which one
answers `canal="whatsapp"` is decided once, at startup, by
`WHATSAPP_PROVIDER` (`whatbot/main.py::_init_infra`). Contacts, history and
`session_state` are keyed by `(canal, external_id)` — the external id is the
same E.164 phone number on both providers, so switching providers needs no
data migration (see `design.md`, "Decisão: mesmo canal whatsapp").

Unlike `InstagramClient`, this client has no local, pre-send messaging-window
check: the WhatsApp Cloud API's own 24h customer-care window is enforced
server-side and only surfaces here as a classified `ChannelError` after the
API rejects a send (`CAUSE_OUTSIDE_WINDOW`) — there is no
`MESSAGING_WINDOWS[WHATSAPP]` entry in `whatbot/channels/base.py` to check
against locally.
"""

from __future__ import annotations

from typing import Any, Dict, List
import logging

import requests

from ..message_log import log_outbound
from .base import WHATSAPP, ChannelError

DEFAULT_BASE_URL = "https://graph.facebook.com"
# Verified against https://developers.facebook.com/docs/graph-api/changelog
# (current stable release as of this change, Aug/2026) — not copied blindly
# from InstagramClient's v23.0, which may be a different point in time.
API_VERSION = "v25.0"

# WhatsApp Cloud API's documented server-side limit for a text message body.
# Meaningfully higher than Instagram Direct's 1000 (`instagram.py`) — kept as
# a safety net / contract symmetry with the other channels, not because bot
# replies are expected to approach it in practice.
MAX_TEXT_LENGTH = 4096

# Transport-level problems worth retrying; an HTTP error means the API
# answered and rejected the request, so repeating it changes nothing on its
# own.
_RETRYABLE = (requests.ConnectionError, requests.Timeout)

# Graph API error codes this client recognizes and translates into a
# `ChannelError` cause. Verified against
# https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
# — `error_subcode` is deprecated for v16.0+ on this API, so classification
# here is by `code` alone, unlike InstagramClient (`graph.instagram.com`,
# a different API surface that still uses `error_subcode`).
_TOKEN_INVALID_CODES = (0, 190, 200)
_RATE_LIMIT_CODES = (4, 80007, 130429, 131056)
_OUTSIDE_WINDOW_CODES = (131047, 131049)
_NOT_OPTED_IN_CODES = (131026, 131050)

CAUSE_INVALID_TOKEN = "invalid_token"
# The Cloud API's own 24h customer-care window (server-side, reactive) —
# distinct concept from Instagram's locally pre-checked messaging window.
CAUSE_OUTSIDE_WINDOW = "outside_window"
CAUSE_RATE_LIMITED = "rate_limited"
CAUSE_NOT_OPTED_IN = "not_opted_in"


def _is_retryable(exc: requests.RequestException) -> bool:
    return isinstance(exc, _RETRYABLE)


def split_text(text: str, limit: int = MAX_TEXT_LENGTH) -> List[str]:
    """Split `text` into ordered blocks no longer than `limit` characters.

    Splits on whitespace boundaries when possible, so words are not cut in
    half; falls back to a hard cut only when a single "word" already exceeds
    the limit. Never returns an empty list for non-empty input. Same
    algorithm as `InstagramClient.split_text` — kept for contract symmetry
    across channels, expected to be a no-op for virtually all real replies
    given the much higher limit here.
    """
    text = text or ""
    limit = max(1, limit)
    if len(text) <= limit:
        return [text] if text else [""]

    blocks: List[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        blocks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        blocks.append(remaining)
    return blocks


def _classify_error(response: requests.Response) -> tuple[str | None, str, str | None]:
    """Return (cause, message, retry_after) derived from a Graph API error response."""
    retry_after = response.headers.get("Retry-After")
    try:
        body = response.json()
    except ValueError:
        body = {}
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None, response.text[:500], retry_after

    message = error.get("message") or response.text[:500]
    code = error.get("code")

    if response.status_code == 429 or code in _RATE_LIMIT_CODES:
        return CAUSE_RATE_LIMITED, message, retry_after
    if code in _TOKEN_INVALID_CODES:
        return CAUSE_INVALID_TOKEN, message, retry_after
    if code in _OUTSIDE_WINDOW_CODES:
        return CAUSE_OUTSIDE_WINDOW, message, retry_after
    if code in _NOT_OPTED_IN_CODES:
        return CAUSE_NOT_OPTED_IN, message, retry_after
    return None, message, retry_after


class WhatsAppCloudClient:
    """WhatsApp channel client backed by Meta's official Cloud API."""

    canal = WHATSAPP

    def __init__(
        self, access_token: str, phone_number_id: str, base_url: str | None = None
    ):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._logger = logging.getLogger("whatbot.whatsapp_cloud_api")

    def _messages_url(self) -> str:
        return f"{self.base_url}/{API_VERSION}/{self.phone_number_id}/messages"

    def _build_payload(self, to: str, text: str) -> Dict[str, Any]:
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }

    def _send_one_block(
        self,
        to: str,
        text: str,
        *,
        source: str,
        contact_id: int | None,
    ) -> Dict[str, Any]:
        url = self._messages_url()
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(to, text)

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
        except requests.RequestException as exc:
            log_outbound(
                to,
                text,
                canal=WHATSAPP,
                source=source,
                contact_id=contact_id,
                delivery="failed",
                error=str(exc),
            )
            self._logger.exception(
                "Erro enviando mensagem via WhatsApp Cloud API: %s", exc
            )
            raise ChannelError(WHATSAPP, str(exc), retryable=_is_retryable(exc)) from exc

        if not response.ok:
            cause, message, retry_after = _classify_error(response)
            self._logger.error(
                "WhatsApp Cloud API %s: %s (cause=%s)",
                response.status_code,
                message,
                cause,
            )
            log_outbound(
                to,
                text,
                canal=WHATSAPP,
                source=source,
                contact_id=contact_id,
                delivery="failed",
                error=message,
                cause=cause,
            )
            error_message = message
            if cause == CAUSE_RATE_LIMITED and retry_after:
                error_message = f"{message} (retry_after={retry_after}s)"
            raise ChannelError(
                WHATSAPP,
                error_message,
                retryable=cause == CAUSE_RATE_LIMITED,
                cause=cause,
            )

        log_outbound(
            to,
            text,
            canal=WHATSAPP,
            source=source,
            contact_id=contact_id,
            delivery="sent",
        )
        return response.json()

    def send_text(
        self,
        to: str,
        text: str,
        *,
        source: str = "bot",
        contact_id: int | None = None,
        simulated: bool = False,
        human_agent: bool = False,  # noqa: ARG002 - WhatsApp Cloud has no messaging window
    ) -> Dict[str, Any]:
        if simulated:
            log_outbound(
                to,
                text,
                canal=WHATSAPP,
                source=source,
                contact_id=contact_id,
                simulated=True,
                delivery="skipped",
            )
            return {"simulated": True}

        blocks = split_text(text)
        results = [
            self._send_one_block(to, block, source=source, contact_id=contact_id)
            for block in blocks
        ]
        if len(results) == 1:
            return results[0]
        return {"blocks": results}
