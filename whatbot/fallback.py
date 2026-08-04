"""Offline replies from the knowledge base when Gemini is unavailable."""

from __future__ import annotations

from .knowledge_facts import get_knowledge_facts, norm_text
from .tools import (
    buscar_faq,
    buscar_horarios_turmas,
    buscar_info_negocio,
    buscar_precos,
    listar_itens,
)


def trim_history_for_chat(history, current_text: str):
    """Drop the latest inbound row when it duplicates the message being processed."""
    if not history:
        return history
    latest = history[0]
    if latest.direction == "in" and latest.text.strip() == current_text.strip():
        return history[1:]
    return history


def build_knowledge_fallback(user_message: str, reason: str = "error") -> str | None:
    """Build a helpful reply using only local knowledge tools (no LLM)."""
    facts = get_knowledge_facts()
    norm = norm_text(user_message)
    parts: list[str] = []
    items = facts.match_items(user_message)
    price_signals = facts.intent_signals.get("precos", set())
    horario_signals = facts.intent_signals.get("horarios", set())
    faq_signals = facts.intent_signals.get("faq", set())

    if items:
        for item in items:
            parts.append(buscar_horarios_turmas(item))
        if any(token in norm for token in price_signals):
            for item in items[:2]:
                parts.append(buscar_precos(item))
    elif any(token in norm for token in price_signals):
        parts.append(buscar_precos(""))
    elif any(token in norm for token in faq_signals if token in {"endereco", "endereço", "onde", "local"}):
        parts.append(buscar_info_negocio("endereço"))
    elif any(token in norm for token in horario_signals):
        parts.append(listar_itens())
    else:
        faq = buscar_faq(user_message)
        if faq and "não encontrei" not in faq.lower() and not faq.strip().startswith("P:"):
            parts.append(faq)

    if not parts:
        listing = listar_itens()
        if listing:
            parts.append(listing)

    body = "\n\n".join(p.strip() for p in parts if p and p.strip())
    if not body:
        return None
    return wrap_fallback_reply(body, reason=reason)


def wrap_fallback_reply(raw: str, reason: str = "error") -> str:
    """Last-resort offline reply — short intro, no FAQ dump format."""
    del reason  # reserved for logging/callers; same user-facing text for all cases
    cleaned = raw.replace("P:", "").replace("R:", "").strip()
    intro = (
        "No momento estou com instabilidade, mas consegui estas informações "
        "oficiais:\n\n"
    )
    outro = (
        "\n\nDigite *quero falar com um atendente* se precisar de ajuda humana."
    )
    return f"{intro}{cleaned}{outro}"
