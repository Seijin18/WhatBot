"""Parse Evolution API webhook payloads into whatbot format."""

from __future__ import annotations

from typing import Any, Dict, Optional


def _extract_text(message: Dict[str, Any]) -> str:
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

    text = _extract_text(data.get("message") or {})

    return {
        "to_number": _normalize_phone(remote_jid),
        "text": text or "[mensagem]",
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

    text = _extract_text(data.get("message") or {})
    if not text:
        return None

    return {
        "from_number": _normalize_phone(remote_jid),
        "text": text,
        "push_name": data.get("pushName"),
        "message_id": key.get("id"),
        "instance": payload.get("instance"),
        "event": payload.get("event"),
    }
