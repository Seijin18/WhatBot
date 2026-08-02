"""Structured logging for inbound/outbound WhatsApp messages and LLM turns."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("whatbot.messages")

ENV_MESSAGE_LOG_PATH = "WHATBOT_MESSAGE_LOG_PATH"
ENV_MESSAGE_LOG_MAX_CHARS = "WHATBOT_MESSAGE_LOG_MAX_CHARS"
DEFAULT_MESSAGE_LOG_MAX_CHARS = 2000


def _max_chars() -> int:
    raw = os.getenv(ENV_MESSAGE_LOG_MAX_CHARS, str(DEFAULT_MESSAGE_LOG_MAX_CHARS))
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_MESSAGE_LOG_MAX_CHARS


def _truncate(text: str | None, max_chars: int | None = None) -> str:
    if not text:
        return ""
    limit = max_chars if max_chars is not None else _max_chars()
    if limit <= 0 or len(text) <= limit:
        return text
    return f"{text[:limit]}… (+{len(text) - limit} chars)"


def _project_root() -> Path:
    """Project root inside Docker (/whatbot) or repo root on the host."""
    docker_root = Path("/whatbot")
    if docker_root.is_dir():
        return docker_root
    return Path(__file__).resolve().parent.parent


def resolve_message_log_path(path: str | None = None) -> Path | None:
    """Resolve WHATBOT_MESSAGE_LOG_PATH relative to the project root."""
    raw = (path or os.getenv(ENV_MESSAGE_LOG_PATH, "")).strip()
    if not raw:
        return None
    resolved = Path(raw)
    if not resolved.is_absolute():
        resolved = _project_root() / resolved
    return resolved


def _log_path() -> Path | None:
    return resolve_message_log_path()


def _write_jsonl(entry: dict[str, Any]) -> None:
    path = _log_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("Falha ao gravar message log em %s: %s", path, exc)


def _emit(entry: dict[str, Any]) -> None:
    entry.setdefault("ts", datetime.now(timezone.utc).isoformat())
    summary = (
        f"canal={entry.get('canal')} "
        f"phone={entry.get('phone')} "
        f"dir={entry.get('direction')} "
        f"source={entry.get('source')} "
        f"len={entry.get('text_len', 0)}"
    )
    if entry.get("kind") == "llm":
        summary = (
            f"canal={entry.get('canal')} "
            f"phone={entry.get('phone')} "
            f"llm={entry.get('llm_provider')} "
            f"fallback={entry.get('used_fallback')} "
            f"reply_len={entry.get('reply_len', 0)}"
        )
    logger.info("%s | %s", entry.get("kind", "message"), summary)
    logger.debug("message_log entry=%s", json.dumps(entry, ensure_ascii=False))
    _write_jsonl(entry)


def log_inbound(
    phone: str,
    text: str,
    *,
    canal: str = "whatsapp",
    push_name: str | None = None,
    contact_id: int | None = None,
    source: str = "customer",
    simulated: bool = False,
    **extra: Any,
) -> None:
    """Log a message received by the bot."""
    _emit(
        {
            "kind": "message",
            "direction": "in",
            "canal": canal,
            "phone": phone,
            "text": _truncate(text),
            "text_len": len(text or ""),
            "push_name": push_name,
            "contact_id": contact_id,
            "source": source,
            "simulated": simulated,
            **extra,
        }
    )


def log_outbound(
    phone: str,
    text: str,
    *,
    canal: str = "whatsapp",
    contact_id: int | None = None,
    source: str = "bot",
    simulated: bool = False,
    delivery: str = "sent",
    **extra: Any,
) -> None:
    """Log a message sent to a channel (or skipped in simulation)."""
    _emit(
        {
            "kind": "message",
            "direction": "out",
            "canal": canal,
            "phone": phone,
            "text": _truncate(text),
            "text_len": len(text or ""),
            "contact_id": contact_id,
            "source": source,
            "simulated": simulated,
            "delivery": delivery,
            **extra,
        }
    )


def log_llm_turn(
    phone: str,
    user_text: str,
    reply: str,
    *,
    canal: str = "whatsapp",
    contact_id: int | None = None,
    contact_status: str | None = None,
    used_fallback: bool = False,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    knowledge_path: str | None = None,
    simulated: bool = False,
    **extra: Any,
) -> None:
    """Log an LLM exchange to trace replies against the knowledge base."""
    _emit(
        {
            "kind": "llm",
            "canal": canal,
            "phone": phone,
            "user_text": _truncate(user_text),
            "user_text_len": len(user_text or ""),
            "reply": _truncate(reply),
            "reply_len": len(reply or ""),
            "contact_id": contact_id,
            "contact_status": contact_status,
            "used_fallback": used_fallback,
            "llm_provider": llm_provider or os.getenv("LLM_PROVIDER", "gemini"),
            "llm_model": llm_model,
            "knowledge_path": knowledge_path or os.getenv(
                "ASSOCIACAO_KNOWLEDGE_PATH", "knowledge/associacao.md"
            ),
            "simulated": simulated,
            **extra,
        }
    )
