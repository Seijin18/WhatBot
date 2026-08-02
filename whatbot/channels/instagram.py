"""Instagram Direct integration for outbound messages.

Uses the "Instagram API with Instagram Login" (host `graph.instagram.com`),
not the Facebook Login variant — see `design.md` in the
`instagram-channel-client` change for why.

This client implements both the *mechanism* for signaling typed failures
(`ChannelError` with a `cause`) and the *policy* of when a send is outside the
messaging window Meta imposes on Instagram Direct (`instagram-messaging-window`):
`send_text` checks `last_inbound_at` — resolved via an injected accessor, not a
direct `whatbot/db.py` dependency, see `design.md` — before dispatching
anything. Domain code (`whatbot/main.py`, `whatbot/domain.py`) never has to
know this policy exists; it only reacts to `ChannelError`, same as any other
channel failure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List
import logging

import requests

from ..message_log import log_outbound
from .base import INSTAGRAM, ChannelError, messaging_window

DEFAULT_BASE_URL = "https://graph.instagram.com"
API_VERSION = "v23.0"

# Instagram Direct's practical text limit; longer replies are split into
# ordered blocks so nothing is silently truncated.
MAX_TEXT_LENGTH = 1000

# Transport-level problems worth retrying; an HTTP error means the API answered
# and rejected the request, so repeating it changes nothing on its own.
_RETRYABLE = (requests.ConnectionError, requests.Timeout)

# Graph API error codes/subcodes this client recognizes and translates into a
# `ChannelError` cause. Anything else falls back to a generic, non-retryable
# `ChannelError` with `cause=None`.
_WINDOW_EXPIRED_SUBCODE = 2534014
_MISSING_PERMISSION_CODE = 10
_RATE_LIMIT_CODE = 613

CAUSE_WINDOW_EXPIRED = "window_expired"
CAUSE_MISSING_HUMAN_AGENT_PERMISSION = "missing_human_agent_permission"
CAUSE_RATE_LIMITED = "rate_limited"
# Fail-closed cause for when the window state cannot even be determined (no
# `last_inbound_lookup` was injected into this client) — distinct from
# `CAUSE_WINDOW_EXPIRED` (we *know* the window is closed) because the caller
# may want to react differently to "unknown" vs. "confirmed closed". See
# `openspec/changes/instagram-messaging-window` Bloqueador 1: the project's
# convention (`identity-multichannel` Decisão 6) is fail-closed, never
# fail-open, on a rule whose violation can get the Instagram account
# suspended.
CAUSE_WINDOW_CHECK_UNAVAILABLE = "window_check_unavailable"

# `(standard_window, human_agent_window)` — single source of truth shared with
# `whatbot/queue.py`, see `whatbot/channels/base.py`.
WINDOW_STANDARD, WINDOW_HUMAN_AGENT = messaging_window(INSTAGRAM)

_WINDOW_EXPIRED_MESSAGE = (
    "Janela de mensageria do Instagram expirada para este contato "
    "(sem last_inbound_at dentro de 24h, ou de 7 dias com atendimento humano)."
)

_WINDOW_CHECK_UNAVAILABLE_MESSAGE = (
    "Não foi possível verificar a janela de mensageria do Instagram para este "
    "contato (cliente sem last_inbound_lookup configurado) — envio bloqueado "
    "por segurança (fail-closed)."
)


def _is_retryable(exc: requests.RequestException) -> bool:
    return isinstance(exc, _RETRYABLE)


def split_text(text: str, limit: int = MAX_TEXT_LENGTH) -> List[str]:
    """Split `text` into ordered blocks no longer than `limit` characters.

    Splits on whitespace boundaries when possible, so words are not cut in
    half; falls back to a hard cut only when a single "word" already exceeds
    the limit. Never returns an empty list for non-empty input.
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
    subcode = error.get("error_subcode")

    if response.status_code == 429 or code == _RATE_LIMIT_CODE:
        return CAUSE_RATE_LIMITED, message, retry_after
    if subcode == _WINDOW_EXPIRED_SUBCODE:
        return CAUSE_WINDOW_EXPIRED, message, retry_after
    if code == _MISSING_PERMISSION_CODE:
        return CAUSE_MISSING_HUMAN_AGENT_PERMISSION, message, retry_after
    return None, message, retry_after


def instagram_last_inbound_lookup(db: Any) -> Callable[[str], "datetime | None"]:
    """Build a `last_inbound_lookup` for `InstagramClient`, fixing `canal=INSTAGRAM`.

    `whatbot/db.py::Database.get_last_inbound_at` requires `canal` as a
    keyword-only argument precisely so it cannot be injected directly as
    `Callable[[str], datetime | None]` without deciding which channel it
    resolves for (see its docstring). This is the intended way to wire it:

        InstagramClient(..., last_inbound_lookup=instagram_last_inbound_lookup(db))

    `db` is typed `Any` (not `whatbot.db.Database`) to avoid this module
    importing `whatbot/db.py` — it only needs an object with a matching
    `get_last_inbound_at(external_id, *, canal)` method (e.g. `Database` or a
    test double), keeping this a small function boundary rather than a
    concrete dependency.
    """

    def lookup(external_id: str) -> "datetime | None":
        return db.get_last_inbound_at(external_id, canal=INSTAGRAM)

    return lookup


class InstagramClient:
    """Instagram Direct channel client backed by the Instagram Graph API."""

    canal = INSTAGRAM

    def __init__(
        self,
        access_token: str,
        account_id: str | None = None,
        base_url: str | None = None,
        *,
        last_inbound_lookup: Callable[[str], "datetime | None"] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.access_token = access_token
        self.account_id = account_id
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._logger = logging.getLogger("whatbot.instagram_api")
        # Small accessor injected by the caller (e.g. `whatbot/main.py`), never
        # a direct `whatbot/db.py` dependency — keeps this client a pure HTTP
        # layer. `None` means the caller wired the client without a way to
        # check the window; `_check_messaging_window` fails *closed* in that
        # case (blocks every send) rather than skipping the check, per the
        # project's fail-closed convention (see `CAUSE_WINDOW_CHECK_UNAVAILABLE`).
        self._last_inbound_lookup = last_inbound_lookup
        # Injectable clock so window tests don't depend on wall-clock time.
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _messages_url(self) -> str:
        return f"{self.base_url}/{API_VERSION}/me/messages"

    def _check_messaging_window(
        self,
        to: str,
        text: str,
        *,
        human_agent: bool,
        source: str,
        contact_id: int | None,
    ) -> None:
        """Raise `ChannelError` if `to` is outside the window.

        Fails *closed*, not open: with no `last_inbound_lookup` injected (see
        `__init__`), this blocks the send with
        `cause=CAUSE_WINDOW_CHECK_UNAVAILABLE` instead of letting it through —
        a violation of the messaging window can get the Instagram account
        suspended, so "I don't know if this is allowed" must behave the same
        as "this is not allowed".

        Contract: `last_inbound_lookup` MUST return a timezone-aware
        `datetime` (or `None`). This client does not normalize naive
        timestamps — subtracting a naive `last_inbound_at` from the
        (timezone-aware) injected clock raises `TypeError` rather than
        silently comparing wrong values. `whatbot/db.py::get_last_inbound_at`
        reads a `TIMESTAMP WITH TIME ZONE` column, so production callers are
        covered; test doubles must inject aware datetimes too.
        """
        if self._last_inbound_lookup is None:
            preview = text[:200] + ("…" if len(text) > 200 else "")
            self._logger.warning(
                "Envio recusado: nenhum last_inbound_lookup injetado neste "
                "InstagramClient, falhando fechado para %s. Mensagem recusada: %r",
                to,
                preview,
            )
            log_outbound(
                to,
                text,
                canal=INSTAGRAM,
                source=source,
                contact_id=contact_id,
                delivery="failed",
                error=_WINDOW_CHECK_UNAVAILABLE_MESSAGE,
                cause=CAUSE_WINDOW_CHECK_UNAVAILABLE,
            )
            raise ChannelError(
                INSTAGRAM,
                _WINDOW_CHECK_UNAVAILABLE_MESSAGE,
                retryable=False,
                cause=CAUSE_WINDOW_CHECK_UNAVAILABLE,
            )

        last_inbound_at = self._last_inbound_lookup(to)
        blocked = last_inbound_at is None
        if not blocked:
            elapsed = self._clock() - last_inbound_at
            # Inclusive boundary (`<=`), deliberately: exactly 24h00m00s (or
            # 7d00h00m00s) still counts as inside the window. Chosen for
            # consistency with `whatbot/queue.py::window_deadline_note`, which
            # uses the same inclusive comparison to decide which note to show
            # for the same elapsed time — an admin should never see "window
            # still open" (queue note) while the client (this check) refuses
            # to send. A ~1-second edge case is not worth risking that
            # mismatch for (reviewed in `instagram-messaging-window` critic
            # pass, kept as-is).
            if elapsed <= WINDOW_STANDARD:
                return
            if elapsed <= WINDOW_HUMAN_AGENT and human_agent:
                return
            blocked = True

        preview = text[:200] + ("…" if len(text) > 200 else "")
        self._logger.warning(
            "Envio recusado: janela de mensageria do Instagram expirada para "
            "%s. Mensagem recusada: %r",
            to,
            preview,
        )
        log_outbound(
            to,
            text,
            canal=INSTAGRAM,
            source=source,
            contact_id=contact_id,
            delivery="failed",
            error=_WINDOW_EXPIRED_MESSAGE,
            cause=CAUSE_WINDOW_EXPIRED,
        )
        raise ChannelError(
            INSTAGRAM,
            _WINDOW_EXPIRED_MESSAGE,
            retryable=False,
            cause=CAUSE_WINDOW_EXPIRED,
        )

    def _build_payload(self, to: str, text: str, *, human_agent: bool) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "recipient": {"id": to},
            "message": {"text": text},
        }
        if human_agent:
            payload["messaging_type"] = "MESSAGE_TAG"
            payload["tag"] = "HUMAN_AGENT"
        return payload

    def _send_one_block(
        self,
        to: str,
        text: str,
        *,
        human_agent: bool,
        source: str,
        contact_id: int | None,
    ) -> Dict[str, Any]:
        url = self._messages_url()
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(to, text, human_agent=human_agent)

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
        except requests.RequestException as exc:
            log_outbound(
                to,
                text,
                canal=INSTAGRAM,
                source=source,
                contact_id=contact_id,
                delivery="failed",
                error=str(exc),
            )
            self._logger.exception("Erro enviando mensagem via Instagram API: %s", exc)
            raise ChannelError(
                INSTAGRAM, str(exc), retryable=_is_retryable(exc)
            ) from exc

        if not response.ok:
            cause, message, retry_after = _classify_error(response)
            self._logger.error(
                "Instagram API %s: %s (cause=%s)",
                response.status_code,
                message,
                cause,
            )
            log_outbound(
                to,
                text,
                canal=INSTAGRAM,
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
                INSTAGRAM,
                error_message,
                retryable=cause == CAUSE_RATE_LIMITED,
                cause=cause,
            )

        log_outbound(
            to,
            text,
            canal=INSTAGRAM,
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
        human_agent: bool = False,
    ) -> Dict[str, Any]:
        if simulated:
            log_outbound(
                to,
                text,
                canal=INSTAGRAM,
                source=source,
                contact_id=contact_id,
                simulated=True,
                delivery="skipped",
            )
            return {"simulated": True}

        self._check_messaging_window(
            to, text, human_agent=human_agent, source=source, contact_id=contact_id
        )

        blocks = split_text(text)
        results = []
        for block in blocks:
            results.append(
                self._send_one_block(
                    to,
                    block,
                    human_agent=human_agent,
                    source=source,
                    contact_id=contact_id,
                )
            )
        if len(results) == 1:
            return results[0]
        return {"blocks": results}
