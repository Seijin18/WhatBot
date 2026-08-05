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

from .channels import InboundMessage, MediaRef, WHATSAPP

# Event classifications produced by `classify_whatsapp_cloud_event`.
KIND_MESSAGE = "message"
KIND_STATUS = "status"
KIND_MEDIA_ONLY = "media_only"
KIND_MALFORMED = "malformed"

# WhatsApp Cloud API message `type`s that carry a media object with an `id`
# field (Graph API media id, used by `WhatsAppCloudClient.download_media`) —
# see https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples.
_MEDIA_TYPES = ("image", "audio", "video", "document", "sticker")


def _extract_text(message: Dict[str, Any]) -> str:
    if not isinstance(message, dict):
        return ""
    if message.get("type") != "text":
        return ""
    body = (message.get("text") or {}).get("body")
    return str(body).strip() if body else ""


def _extract_media(message: Dict[str, Any]) -> MediaRef | None:
    """Return the `MediaRef` for a media message, or `None` for a text one.

    `conversation-history-media-storage`: previously mídia era descartada
    inteiramente (evento classificado `KIND_MEDIA_ONLY` produzia
    `data=None`) — agora essa referência é o que permite baixar e persistir
    o binário em `whatbot/main.py`.
    """
    if not isinstance(message, dict):
        return None
    tipo = message.get("type")
    if tipo not in _MEDIA_TYPES:
        return None
    media_obj = message.get(tipo)
    if not isinstance(media_obj, dict):
        return None
    media_id = media_obj.get("id")
    if not media_id:
        return None
    return MediaRef(
        tipo=tipo,
        provider_media_id=str(media_id),
        mime_type=media_obj.get("mime_type"),
        caption=media_obj.get("caption"),
    )


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


def parse_whatsapp_cloud_media_message(
    value: Dict[str, Any],
    event: Dict[str, Any],
    payload: Dict[str, Any] | None = None,
) -> Optional[Dict[str, Any]]:
    """Parse a single media-only event (`KIND_MEDIA_ONLY`), or `None` if it
    is not one.

    Mirrors `parse_whatsapp_cloud_message` — same normalized shape
    (`InboundMessage.to_payload()`), except `text` is empty and `media`
    carries the provider's media reference for later download
    (`whatbot/main.py`, `WhatsAppCloudClient.download_media`).
    """
    if classify_whatsapp_cloud_event(event) != KIND_MEDIA_ONLY:
        return None
    media = _extract_media(event)
    if media is None:
        return None

    sender_id = event["from"]
    inbound = InboundMessage(
        canal=WHATSAPP,
        external_id=sender_id,
        text="",
        display_name=_display_name(value, sender_id),
        message_id=event.get("id"),
        raw=payload,
        media=media,
    )
    return {
        **inbound.to_payload(),
        "timestamp": event.get("timestamp"),
    }


def parse_whatsapp_cloud_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse a full WhatsApp Cloud API webhook POST into classified events.

    A single POST can bundle multiple `entry`/`changes` items; every one is
    processed — none is dropped silently. Each result is
    `{"kind": ..., "data": ...}`: `data` is the parsed payload for `message`
    and `media_only` events (the latter carrying a `media` reference instead
    of text — see `parse_whatsapp_cloud_media_message`), `None` for `status`
    and `malformed` events, since there is nothing to act on beyond the
    classification itself.
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
                elif kind == KIND_MEDIA_ONLY:
                    data = parse_whatsapp_cloud_media_message(value, event, payload)
                results.append({"kind": kind, "data": data})
    return results
