"""Parse Evolution API webhook payloads into whatbot format."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .channels import WHATSAPP, InboundMessage


def _extract_order(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract a WhatsApp catalog order from an inbound message, if present.

    See openspec/changes/catalog-order-capture/design.md (Decisão 2):
    `items_identifiable` is derived from data presence (a `productId` on
    every item), not from detecting the sending platform directly — Android
    orders typically carry identifiable items, iOS orders typically don't
    (evolution-foundation/evolution-api#1819), but this stays correct even
    if the underlying cause changes in the future.
    """
    if not message or "orderMessage" not in message:
        return None
    # `orderMessage` present but empty/`None` (e.g. `{"orderMessage": {}}`)
    # is still a real order, just with no data — must not be treated as
    # "no order" (which would fall the message back into the original
    # silent-drop bug this change fixes).
    order_message = message.get("orderMessage") or {}
    items = order_message.get("items") or []
    items_identifiable = bool(items) and all(
        item.get("productId") for item in items
    )
    return {
        "order_id": order_message.get("orderId"),
        "item_count": order_message.get("itemCount", len(items)),
        "order_title": order_message.get("orderTitle"),
        "items": items,
        "items_identifiable": items_identifiable,
    }


def _extract_text(
    message: Dict[str, Any], order: Optional[Dict[str, Any]] = None
) -> str:
    """`order`, when the caller already computed it (`parse_evolution_payload`),
    is reused instead of recomputing via `_extract_order(message)` — avoids
    parsing the same `orderMessage` twice per payload. Callers that don't
    care about orders (e.g. `parse_outgoing_staff_message`) can omit it;
    it's derived from `message` on demand."""
    if not message:
        return ""
    if conversation := message.get("conversation"):
        return str(conversation).strip()
    if extended := message.get("extendedTextMessage"):
        return str(extended.get("text", "")).strip()
    if image := message.get("imageMessage"):
        return str(image.get("caption", "")).strip()
    if video := message.get("videoMessage"):
        return str(video.get("caption", "")).strip()
    if buttons := message.get("buttonsResponseMessage"):
        return str(buttons.get("selectedDisplayText", "")).strip()
    if list_response := message.get("listResponseMessage"):
        title = list_response.get("title", "")
        description = list_response.get("description", "")
        return f"{title} {description}".strip()
    if order is None:
        order = _extract_order(message)
    if order:
        # Never empty: an `orderMessage` must never be silently dropped by
        # the `if not text: return None` guard in `parse_evolution_payload`
        # (openspec/changes/catalog-order-capture/proposal.md, "Why").
        if order["items_identifiable"]:
            return f"[pedido do catálogo] {order['item_count']} item(ns)"
        return "[pedido do catálogo] itens não identificados"
    return ""


def _normalize_phone(remote_jid: str) -> str:
    phone = remote_jid.split("@", 1)[0]
    if phone.endswith("-"):
        phone = phone.rsplit("-", 1)[0]
    return phone


def parse_outgoing_staff_message(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse a fromMe message (secretariat reply) sent to a customer."""
    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    key = data.get("key") or {}
    if not key.get("fromMe"):
        return None

    remote_jid = key.get("remoteJid") or ""
    if not remote_jid or remote_jid.endswith("@g.us"):
        return None

    echo = InboundMessage(
        canal=WHATSAPP,
        external_id=_normalize_phone(remote_jid),
        text=_extract_text(data.get("message") or {}) or "[mensagem]",
        message_id=key.get("id"),
        is_echo=True,
        raw=payload,
    )

    # An echo travels outbound, so it carries `to_number` rather than the
    # inbound `from_number` that `to_payload()` produces.
    return {
        "canal": echo.canal,
        "to_number": echo.external_id,
        "text": echo.text,
        "from_me": True,
        "instance": payload.get("instance"),
        "event": payload.get("event"),
    }


def parse_evolution_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert an Evolution API webhook body into whatbot's expected payload."""
    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    key = data.get("key") or {}
    if key.get("fromMe"):
        return None

    remote_jid = key.get("remoteJid") or ""
    if not remote_jid or remote_jid.endswith("@g.us"):
        return None

    raw_message = data.get("message") or {}
    order = _extract_order(raw_message)
    text = _extract_text(raw_message, order=order)
    if not text:
        return None

    message = InboundMessage(
        canal=WHATSAPP,
        external_id=_normalize_phone(remote_jid),
        text=text,
        display_name=data.get("pushName"),
        message_id=key.get("id"),
        raw=payload,
    )

    return {
        **message.to_payload(),
        "instance": payload.get("instance"),
        "event": payload.get("event"),
        # `order` (a dict, `None` when this isn't a catalog order) is a
        # deliberate free-standing key on this returned dict, not a field on
        # `InboundMessage` — see
        # openspec/changes/catalog-order-capture/design.md, Decisão 1.
        "order": order,
    }
