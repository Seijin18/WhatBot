"""Evolution API integration for outbound WhatsApp messages."""

from __future__ import annotations

from typing import Any, Dict
import logging

import requests

from .config import EVOLUTION_API_BASE_URL


class EvolutionApiClient:
    def __init__(self, api_key: str, instance_name: str, base_url: str | None = None):
        self.api_key = api_key
        self.instance_name = instance_name
        self.base_url = (base_url or EVOLUTION_API_BASE_URL).rstrip("/")
        self._logger = logging.getLogger("whatbot.evolution_api")

    def send_text(self, to_phone: str, text: str) -> Dict[str, Any]:
        url = f"{self.base_url}/message/sendText/{self.instance_name}"
        headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "number": to_phone,
            "text": text,
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if not response.ok:
                self._logger.error(
                    "Evolution API %s: %s",
                    response.status_code,
                    response.text[:500],
                )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            self._logger.exception("Erro enviando mensagem via Evolution API: %s", exc)
            raise


# Backward-compatible alias for the rest of the application.
WhatsAppClient = EvolutionApiClient
