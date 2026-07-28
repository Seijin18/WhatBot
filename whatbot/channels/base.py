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
        payload: Dict[str, Any] = {
            "canal": self.canal,
            "external_id": self.external_id,
            "text": self.text,
            "push_name": self.display_name,
            "message_id": self.message_id,
        }
        if self.canal == WHATSAPP:
            payload["from_number"] = self.external_id
        return payload


class ChannelError(RuntimeError):
    """Raised when a channel cannot deliver a message."""

    def __init__(self, canal: str, message: str, *, retryable: bool = False):
        super().__init__(f"[{canal}] {message}")
        self.canal = canal
        self.retryable = retryable


class UnknownChannelError(ChannelError):
    """Raised when no client is registered for a channel."""

    def __init__(self, canal: str, registered: tuple[str, ...] = ()):
        detail = f"canal não registrado no roteador (registrados: {', '.join(registered) or 'nenhum'})"
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
