"""Deprecated shim — kept so existing imports keep working.

The Evolution API client now lives in `whatbot.channels.whatsapp_evolution`.
New code should import from `whatbot.channels` and route through
`whatbot.channels.ChannelRouter` instead of holding a client directly.
"""

from __future__ import annotations

from .channels.whatsapp_evolution import EvolutionApiClient, WhatsAppClient

__all__ = ["EvolutionApiClient", "WhatsAppClient"]
