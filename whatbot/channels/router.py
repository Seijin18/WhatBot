"""Outbound routing: pick the right channel client for each recipient.

`ChannelRouter` is a drop-in replacement for a single channel client: it exposes
the same `send_text` signature plus an optional `canal` keyword. Code that used
to hold an `EvolutionApiClient` can hold a router instead with no behaviour
change, because an unspecified channel resolves to the default (WhatsApp).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List

from .base import (
    ADMIN_CHANNEL,
    DEFAULT_CHANNEL,
    ChannelClient,
    UnknownChannelError,
    normalize_channel,
)

logger = logging.getLogger("whatbot.channels")


class ChannelRouter:
    """Registry of channel clients, resolved by channel name."""

    def __init__(
        self,
        clients: Iterable[ChannelClient] = (),
        *,
        default_channel: str = DEFAULT_CHANNEL,
        admin_channel: str = ADMIN_CHANNEL,
    ):
        self._clients: Dict[str, ChannelClient] = {}
        self.default_channel = normalize_channel(default_channel)
        self.admin_channel = normalize_channel(admin_channel)
        for client in clients:
            self.register(client)

    def register(self, client: ChannelClient) -> "ChannelRouter":
        canal = normalize_channel(getattr(client, "canal", None))
        self._clients[canal] = client
        logger.info("Canal registrado: %s (%s)", canal, type(client).__name__)
        return self

    @property
    def channels(self) -> List[str]:
        return sorted(self._clients)

    def has(self, canal: str | None) -> bool:
        return normalize_channel(canal) in self._clients

    def client_for(self, canal: str | None = None) -> ChannelClient:
        resolved = normalize_channel(canal or self.default_channel)
        client = self._clients.get(resolved)
        if client is None:
            raise UnknownChannelError(resolved, tuple(self.channels))
        return client

    def send_text(
        self,
        to: str,
        text: str,
        *,
        canal: str | None = None,
        source: str = "bot",
        contact_id: int | None = None,
        simulated: bool = False,
        human_agent: bool = False,
    ) -> Dict[str, Any]:
        return self.client_for(canal).send_text(
            to,
            text,
            source=source,
            contact_id=contact_id,
            simulated=simulated,
            human_agent=human_agent,
        )

    def send_admin_text(
        self,
        to: str,
        text: str,
        *,
        source: str = "admin",
        contact_id: int | None = None,
        simulated: bool = False,
    ) -> Dict[str, Any]:
        """Admins are always reached on the admin channel, whatever the customer used."""
        return self.send_text(
            to,
            text,
            canal=self.admin_channel,
            source=source,
            contact_id=contact_id,
            simulated=simulated,
        )


def _routes_by_channel(target: Any) -> bool:
    """Whether `target` is a router rather than a single channel client.

    Detected by capability, not concrete type, so that any object implementing
    the routing surface keeps `canal` and `human_agent` instead of silently
    losing them.
    """
    return hasattr(target, "send_admin_text")


def send_admin(target: Any, to: str, text: str, *, source: str = "admin") -> Dict[str, Any]:
    """Send to an admin, accepting either a router or a bare channel client."""
    if _routes_by_channel(target):
        return target.send_admin_text(to, text, source=source)
    return target.send_text(to, text, source=source)


def send_to_contact(
    target: Any,
    to: str,
    text: str,
    *,
    canal: str | None = None,
    source: str = "bot",
    contact_id: int | None = None,
    simulated: bool = False,
    human_agent: bool = False,
) -> Dict[str, Any]:
    """Send to a customer, accepting either a router or a bare channel client."""
    if _routes_by_channel(target):
        return target.send_text(
            to,
            text,
            canal=canal,
            source=source,
            contact_id=contact_id,
            simulated=simulated,
            human_agent=human_agent,
        )
    return target.send_text(
        to,
        text,
        source=source,
        contact_id=contact_id,
        simulated=simulated,
    )
