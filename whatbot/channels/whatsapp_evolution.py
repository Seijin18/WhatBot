"""Evolution API integration for outbound WhatsApp messages."""

from __future__ import annotations

from typing import Any, Dict
import logging

import requests

from ..config import EVOLUTION_API_BASE_URL
from ..message_log import log_outbound
from .base import WHATSAPP, ChannelError

# Transport-level problems worth retrying; an HTTP error means the API answered
# and rejected the request, so repeating it changes nothing.
_RETRYABLE = (requests.ConnectionError, requests.Timeout)


def _is_retryable(exc: requests.RequestException) -> bool:
    return isinstance(exc, _RETRYABLE)


class EvolutionApiClient:
    """WhatsApp channel client backed by the Evolution API (Baileys)."""

    canal = WHATSAPP

    def __init__(self, api_key: str, instance_name: str, base_url: str | None = None):
        self.api_key = api_key
        self.instance_name = instance_name
        self.base_url = (base_url or EVOLUTION_API_BASE_URL).rstrip("/")
        self._logger = logging.getLogger("whatbot.evolution_api")

    def send_text(
        self,
        to: str,
        text: str,
        *,
        source: str = "bot",
        contact_id: int | None = None,
        simulated: bool = False,
        human_agent: bool = False,  # noqa: ARG002 - WhatsApp has no messaging window
    ) -> Dict[str, Any]:
        to_phone = to
        url = f"{self.base_url}/message/sendText/{self.instance_name}"
        headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "number": to_phone,
            "text": text,
        }

        if simulated:
            log_outbound(
                to_phone,
                text,
                source=source,
                contact_id=contact_id,
                simulated=True,
                delivery="skipped",
            )
            return {"simulated": True}

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if not response.ok:
                self._logger.error(
                    "Evolution API %s: %s",
                    response.status_code,
                    response.text[:500],
                )
            response.raise_for_status()
            log_outbound(
                to_phone,
                text,
                source=source,
                contact_id=contact_id,
                delivery="sent",
            )
            return response.json()
        except requests.RequestException as exc:
            log_outbound(
                to_phone,
                text,
                source=source,
                contact_id=contact_id,
                delivery="failed",
                error=str(exc),
            )
            self._logger.exception("Erro enviando mensagem via Evolution API: %s", exc)
            raise ChannelError(
                WHATSAPP, str(exc), retryable=_is_retryable(exc)
            ) from exc


# Backward-compatible alias for the rest of the application.
WhatsAppClient = EvolutionApiClient
