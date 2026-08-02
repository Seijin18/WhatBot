"""Channel abstraction: the contract every messaging channel must satisfy.

This module is deliberately dependency-free so it can be imported from anywhere
in the package (config, db, main) without creating import cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol, runtime_checkable

WHATSAPP = "whatsapp"
INSTAGRAM = "instagram"

DEFAULT_CHANNEL = WHATSAPP
ADMIN_CHANNEL = WHATSAPP  # a secretaria sempre é notificada pelo WhatsApp
SUPPORTED_CHANNELS = (WHATSAPP, INSTAGRAM)

CHANNEL_LABELS = {
    WHATSAPP: "WhatsApp",
    INSTAGRAM: "Instagram",
}


def normalize_channel(canal: str | None) -> str:
    """Normalize a channel name, falling back to the default channel."""
    if not canal:
        return DEFAULT_CHANNEL
    normalized = canal.strip().lower()
    return normalized or DEFAULT_CHANNEL


def validate_channel(canal: str | None) -> str:
    """Normalize and reject a channel the application does not support.

    Meant for the inbound edge: an unknown channel should stop the request where
    it arrives, before touching the database or the model, instead of surfacing
    much later as a routing failure.
    """
    normalized = normalize_channel(canal)
    if normalized not in SUPPORTED_CHANNELS:
        raise UnknownChannelError(
            normalized, SUPPORTED_CHANNELS, reason="canal não suportado"
        )
    return normalized


def channel_label(canal: str | None) -> str:
    """Human-readable channel name for admin messages."""
    return CHANNEL_LABELS.get(normalize_channel(canal), normalize_channel(canal))


@dataclass
class InboundMessage:
    """A message received from any channel, already normalized.

    `external_id` is the channel-scoped identity of the customer: a phone number
    on WhatsApp, an Instagram-scoped user ID (IGSID) on Instagram.
    """

    canal: str
    external_id: str
    text: str
    display_name: str | None = None
    message_id: str | None = None
    is_echo: bool = False
    raw: Dict[str, Any] | None = None

    def to_payload(self) -> Dict[str, Any]:
        """Legacy whatbot payload shape, kept for `whatbot.main.main()`."""
        canal = normalize_channel(self.canal)
        payload: Dict[str, Any] = {
            "canal": canal,
            "external_id": self.external_id,
            "text": self.text,
            "push_name": self.display_name,
            "message_id": self.message_id,
        }
        if canal == WHATSAPP:
            payload["from_number"] = self.external_id
        return payload


class ChannelError(RuntimeError):
    """Raised when a channel cannot deliver a message.

    `cause` is an optional, channel-defined identifier for *why* delivery was
    refused (e.g. `"window_expired"`, `"missing_human_agent_permission"`,
    `"rate_limited"`), so callers can react to specific failure modes without
    parsing the message string. `None` means the failure has no such
    identified cause (e.g. a generic transport failure).
    """

    def __init__(
        self,
        canal: str,
        message: str,
        *,
        retryable: bool = False,
        cause: str | None = None,
    ):
        super().__init__(f"[{canal}] {message}")
        self.canal = canal
        self.retryable = retryable
        self.cause = cause


class UnknownChannelError(ChannelError):
    """Raised for a channel the application cannot handle.

    Either it is not supported at all (rejected at the inbound edge) or no
    client is registered for it in the router.
    """

    def __init__(
        self,
        canal: str,
        known: tuple[str, ...] = (),
        *,
        reason: str = "canal não registrado no roteador",
    ):
        detail = f"{reason} (conhecidos: {', '.join(known) or 'nenhum'})"
        super().__init__(canal or "?", detail)


@runtime_checkable
class ChannelClient(Protocol):
    """Outbound contract implemented by every channel client."""

    canal: str

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
        """Send a plain-text message.

        `human_agent` requests delivery under a human-agent allowance when the
        channel enforces a messaging window (Instagram). Channels without such a
        window ignore it.
        """
        ...
