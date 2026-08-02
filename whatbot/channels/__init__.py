"""Messaging channels: abstraction, clients and outbound routing."""

from .base import (
    ADMIN_CHANNEL,
    CHANNEL_LABELS,
    DEFAULT_CHANNEL,
    INSTAGRAM,
    MESSAGING_WINDOWS,
    SUPPORTED_CHANNELS,
    WHATSAPP,
    ChannelClient,
    ChannelError,
    InboundMessage,
    UnknownChannelError,
    channel_label,
    messaging_window,
    normalize_channel,
    validate_channel,
)
from .router import ChannelRouter, send_admin, send_to_contact
from .whatsapp_evolution import EvolutionApiClient, WhatsAppClient

__all__ = [
    "ADMIN_CHANNEL",
    "CHANNEL_LABELS",
    "DEFAULT_CHANNEL",
    "INSTAGRAM",
    "MESSAGING_WINDOWS",
    "SUPPORTED_CHANNELS",
    "WHATSAPP",
    "ChannelClient",
    "ChannelError",
    "ChannelRouter",
    "EvolutionApiClient",
    "InboundMessage",
    "UnknownChannelError",
    "WhatsAppClient",
    "channel_label",
    "messaging_window",
    "normalize_channel",
    "send_admin",
    "send_to_contact",
    "validate_channel",
]
