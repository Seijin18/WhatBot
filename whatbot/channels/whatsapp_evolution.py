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

    def fetch_catalog(self) -> list[Dict[str, Any]]:
        """Fetch the WhatsApp Business catalog (catalog-product-sync).

        `POST /chat/fetchCatalogs/{instance}` is not officially documented by
        Meta — it is Evolution API's reverse-engineering of Baileys' WhatsApp
        Web catalog read (see `openspec/changes/catalog-product-sync/
        proposal.md`, "Why"). This is a read, not a send: unlike `send_text`,
        a failure is not wrapped in `ChannelError` (that type is the sending
        contract) — it simply propagates as `requests.RequestException`, which
        `whatbot.main.sync_catalog()` (the only caller) catches so a sync
        failure never blocks customer traffic. Everything that can go wrong
        while turning the response into `list[dict]` — HTTP error, transport
        error, unexpected JSON shape — happens inside the same `try`, so this
        promise actually holds (see critic feedback on catalog-product-sync:
        the normalization step used to run outside the `try`, where a
        non-dict raw item would raise `AttributeError` instead).

        Returns a list already shaped for `Database.upsert_catalog_products`
        (`product_id`, `nome`, `preco`, `disponivel`), normalized from the raw
        catalog item fields Baileys exposes (`id`/`retailerId`, `name`,
        `price`, `isHidden`) — the same `id` that shows up as `productId` on
        `orderMessage` items (see `whatbot/webhook.py`). A malformed raw item
        (not a dict, or with no recognizable id field) is logged as a warning
        and dropped, not raised — one bad product in the response must never
        cost every other valid product in the same batch (see
        `_normalize_catalog_items`).
        """
        url = f"{self.base_url}/chat/fetchCatalogs/{self.instance_name}"
        headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(url, headers=headers, json={}, timeout=10)
            if not response.ok:
                self._logger.error(
                    "Evolution API %s: %s",
                    response.status_code,
                    response.text[:500],
                )
            response.raise_for_status()
            raw_items = response.json()
            if isinstance(raw_items, dict):
                raw_items = raw_items.get("catalog") or raw_items.get("products") or []
            return self._normalize_catalog_items(raw_items)
        except requests.RequestException as exc:
            self._logger.exception("Erro buscando catálogo via Evolution API: %s", exc)
            raise

    def _normalize_catalog_items(self, raw_items: Any) -> list[Dict[str, Any]]:
        """Map raw catalog entries to `produtos_catalogo` shape, dropping bad ones.

        A single malformed entry — not a `dict`, or missing every field this
        integration recognizes as a product id (`id`/`retailerId`/
        `productId`) — must never abort the whole sync batch nor keep failing
        on every run just because one remote product is malformed: it is
        logged as a warning and skipped, every other valid product in the
        same response is still returned and persisted.
        """
        products: list[Dict[str, Any]] = []
        for item in raw_items or []:
            if not isinstance(item, dict) or not item:
                self._logger.warning(
                    "Item de catálogo ignorado: formato inesperado (%r)", item
                )
                continue
            product = self._to_catalog_product(item)
            if not product["product_id"]:
                self._logger.warning(
                    "Item de catálogo ignorado: sem id/retailerId/productId "
                    "reconhecível (%r)",
                    item,
                )
                continue
            products.append(product)
        return products

    @staticmethod
    def _to_catalog_product(item: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize one raw catalog item.

        ASSUNÇÃO NÃO VALIDADA (ver proposal.md "Why" — endpoint não
        documentado oficialmente pela Meta): `preco` é copiado de `price`
        sem qualquer conversão de escala. Não há confirmação, sem uma
        instância real da Evolution API para inspecionar, de que `price`
        venha em unidade decimal (ex.: 49.90) em vez da menor unidade da
        moeda (centavos, ex.: 4990) — revisar esta suposição assim que o job
        rodar contra um catálogo real (ver tasks.md, nota da tarefa 1.1).
        """
        product_id = item.get("id") or item.get("retailerId") or item.get("productId")
        return {
            "product_id": str(product_id) if product_id else None,
            "nome": item.get("name") or item.get("nome"),
            "preco": item.get("price", item.get("preco")),
            "disponivel": not bool(item.get("isHidden", False)),
        }


# Backward-compatible alias for the rest of the application.
WhatsAppClient = EvolutionApiClient
