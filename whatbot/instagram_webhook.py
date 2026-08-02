"""Parse Instagram webhook payloads (Instagram API with Instagram Login) into
whatbot's normalized `InboundMessage` shape.

Mirrors `whatbot/webhook.py` (the WhatsApp/Evolution parser): the customer
event and the "own account replied" echo event are parsed into the same
`InboundMessage` contract, and the payload derived via `to_payload()`/an
echo-shaped dict is what the rest of the system consumes.

A single Instagram webhook POST can bundle several `entry` items, each with
several `messaging` events — unlike the Evolution API, which sends one event
per POST. `parse_instagram_payload` is the entry point that iterates all of
them; the single-event helpers (`parse_instagram_message`,
`parse_instagram_echo`) mirror the WhatsApp module's shape for direct testing
and reuse.

Edge cases handled without raising: story mention/reply, media-only message
(no text), deleted-message notification, the secretariat's own reply echoed
back by the Instagram app, and malformed/incomplete events. Each is
classified explicitly (see `classify_instagram_event`) so a caller can tell
"legitimately nothing to do here" apart from "this event could not be
parsed" — see Requirement "Parser reconhece formatos e casos de borda do
Instagram" in `openspec/changes/instagram-channel-client/specs/instagram/spec.md`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .channels import INSTAGRAM, InboundMessage

# Event classifications produced by `classify_instagram_event`.
KIND_MESSAGE = "message"
KIND_ECHO = "echo"
KIND_DELETED = "deleted"
KIND_STORY = "story"
KIND_MEDIA_ONLY = "media_only"
KIND_MALFORMED = "malformed"


def _extract_text(message: Dict[str, Any]) -> str:
    if not message:
        return ""
    text = message.get("text")
    return str(text).strip() if text else ""


def _has_story_reference(message: Dict[str, Any]) -> bool:
    """True for a story mention or a reply to a story.

    Both arrive with a different payload shape than a regular DM (no plain
    `text`, or a `reply_to.story` block instead) and must not be mistaken for
    a media-only message or fall through to the parser as if it were text.
    """
    reply_to = message.get("reply_to") or {}
    if isinstance(reply_to, dict) and reply_to.get("story"):
        return True
    for attachment in message.get("attachments") or []:
        if isinstance(attachment, dict) and attachment.get("type") == "story_mention":
            return True
    return False


def classify_instagram_event(event: Any) -> str:
    """Classify a single `messaging` event from an Instagram webhook payload."""
    if not isinstance(event, dict):
        return KIND_MALFORMED
    message = event.get("message")
    if not isinstance(message, dict):
        return KIND_MALFORMED

    if message.get("is_deleted"):
        return KIND_DELETED
    if message.get("is_echo"):
        if not isinstance(event.get("recipient"), dict) or not event["recipient"].get("id"):
            return KIND_MALFORMED
        return KIND_ECHO
    if not isinstance(event.get("sender"), dict) or not event["sender"].get("id"):
        return KIND_MALFORMED
    if _has_story_reference(message):
        return KIND_STORY
    if _extract_text(message):
        return KIND_MESSAGE
    return KIND_MEDIA_ONLY


def parse_instagram_message(
    event: Dict[str, Any], payload: Dict[str, Any] | None = None
) -> Optional[Dict[str, Any]]:
    """Parse a single customer-message event, or `None` if it is not one.

    `None` covers both "not applicable" (echo, deleted, story reference,
    media-only) and malformed input — callers that need to distinguish those
    should use `classify_instagram_event` first.
    """
    if classify_instagram_event(event) != KIND_MESSAGE:
        return None

    message = event["message"]
    sender_id = event["sender"]["id"]
    inbound = InboundMessage(
        canal=INSTAGRAM,
        external_id=sender_id,
        text=_extract_text(message),
        message_id=message.get("mid"),
        raw=payload,
    )
    return {
        **inbound.to_payload(),
        "timestamp": event.get("timestamp"),
    }


def parse_instagram_echo(
    event: Dict[str, Any], payload: Dict[str, Any] | None = None
) -> Optional[Dict[str, Any]]:
    """Parse a single echo event (own account replying, e.g. via the app).

    Mirrors `whatbot.webhook.parse_outgoing_staff_message`: recognized as
    confirmation of human handling, not routed back through the bot.
    """
    if classify_instagram_event(event) != KIND_ECHO:
        return None

    message = event["message"]
    recipient_id = event["recipient"]["id"]
    echo = InboundMessage(
        canal=INSTAGRAM,
        external_id=recipient_id,
        text=_extract_text(message) or "[mensagem]",
        message_id=message.get("mid"),
        is_echo=True,
        raw=payload,
    )
    # An echo travels outbound, so it carries `to_number` rather than the
    # inbound `from_number` that `to_payload()` produces — same convention as
    # `parse_outgoing_staff_message`.
    return {
        "canal": echo.canal,
        "to_number": echo.external_id,
        "text": echo.text,
        "from_me": True,
        "timestamp": event.get("timestamp"),
    }


def parse_instagram_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse a full Instagram webhook POST into a list of classified events.

    A single POST can bundle multiple `entry` items, each with multiple
    `messaging` events; every one of them is processed — none is dropped
    silently. Each result is `{"kind": ..., "data": ...}`: `data` is the
    parsed payload for `message`/`echo` events, `None` for every other kind
    (deleted, story, media-only, malformed) since there is nothing to act on
    beyond the classification itself.
    """
    results: List[Dict[str, Any]] = []
    if not isinstance(payload, dict) or payload.get("object") != "instagram":
        return results

    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for event in entry.get("messaging") or []:
            kind = classify_instagram_event(event)
            data: Optional[Dict[str, Any]] = None
            if kind == KIND_MESSAGE:
                data = parse_instagram_message(event, payload)
            elif kind == KIND_ECHO:
                data = parse_instagram_echo(event, payload)
            results.append({"kind": kind, "data": data})
    return results
