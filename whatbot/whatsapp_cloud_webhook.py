"""Parse WhatsApp Cloud API webhook payloads into whatbot's normalized
`InboundMessage` shape.

Mirrors `whatbot/instagram_webhook.py`, adapted to the Cloud API's payload
shape — `entry[].changes[].value.{messages[],statuses[],contacts[]}` —
which is structurally different from Instagram's `entry[].messaging[]`
despite both being Meta webhook products sharing the same `hub.challenge`
handshake (`whatbot/ingress.py`).

A single POST can bundle multiple `entry`/`changes` items, each with
multiple `messages`; `parse_whatsapp_cloud_payload` is the entry point that
iterates all of them. `statuses` events (delivery/read receipts) are
recognized and classified but never produce an `InboundMessage` — they are
not a new customer message, and treating them as one would generate a bot
reply to an acknowledgment.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .channels import InboundMessage, WHATSAPP

# Event classifications produced by `classify_whatsapp_cloud_event`.
KIND_MESSAGE = "message"
KIND_STATUS = "status"
KIND_MEDIA_ONLY = "media_only"
KIND_MALFORMED = "malformed"


def _extract_text(message: Dict[str, Any]) -> str:
    if not isinstance(message, dict):
        return ""
    if message.get("type") != "text":
        return ""
    body = (message.get("text") or {}).get("body")
    return str(body).strip() if body else ""


def _display_name(value: Dict[str, Any], sender_id: str) -> Optional[str]:
    for contact in value.get("contacts") or []:
        if not isinstance(contact, dict):
            continue
        if contact.get("wa_id") == sender_id:
            profile = contact.get("profile") or {}
            name = profile.get("name")
            return str(name) if name else None
    return None


def classify_whatsapp_cloud_event(event: Any) -> str:
    """Classify a single `messages[]` entry from a Cloud API webhook payload."""
    if not isinstance(event, dict):
        return KIND_MALFORMED
    if not event.get("from") or not event.get("id") or not event.get("type"):
        return KIND_MALFORMED
    if _extract_text(event):
        return KIND_MESSAGE
    return KIND_MEDIA_ONLY


def parse_whatsapp_cloud_message(
    value: Dict[str, Any],
    event: Dict[str, Any],
    payload: Dict[str, Any] | None = None,
) -> Optional[Dict[str, Any]]:
    """Parse a single customer-message event, or `None` if it is not one.

    `None` covers both "not applicable" (media-only) and malformed input —
    callers that need to distinguish those should use
    `classify_whatsapp_cloud_event` first.
    """
    if classify_whatsapp_cloud_event(event) != KIND_MESSAGE:
        return None

    sender_id = event["from"]
    inbound = InboundMessage(
        canal=WHATSAPP,
        external_id=sender_id,
        text=_extract_text(event),
        display_name=_display_name(value, sender_id),
        message_id=event.get("id"),
        raw=payload,
    )
    # `to_payload()` already injects "from_number" for canal==WHATSAPP
    # (`whatbot/channels/base.py`), so nothing extra is needed here — same
    # payload shape the Evolution API parser produces, main.py's dispatch
    # doesn't need to know which provider originated it.
    return {
        **inbound.to_payload(),
        "timestamp": event.get("timestamp"),
    }


def parse_whatsapp_cloud_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse a full WhatsApp Cloud API webhook POST into classified events.

    A single POST can bundle multiple `entry`/`changes` items; every one is
    processed — none is dropped silently. Each result is
    `{"kind": ..., "data": ...}`: `data` is the parsed payload for `message`
    events, `None` for every other kind (status, media_only, malformed)
    since there is nothing to act on beyond the classification itself.
    """
    results: List[Dict[str, Any]] = []
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return results

    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue

            # A `statuses` batch (delivery/read acks) is not a new message —
            # classified once per batch, no per-status iteration needed: the
            # spec only requires that no `InboundMessage` is produced, not
            # that each individual ack be processed.
            if value.get("statuses"):
                results.append({"kind": KIND_STATUS, "data": None})

            for event in value.get("messages") or []:
                kind = classify_whatsapp_cloud_event(event)
                data: Optional[Dict[str, Any]] = None
                if kind == KIND_MESSAGE:
                    data = parse_whatsapp_cloud_message(value, event, payload)
                results.append({"kind": kind, "data": data})
    return results
