"""Offline replies from the knowledge base when Gemini is unavailable."""

from __future__ import annotations

import unicodedata

from .tools import (
    buscar_faq,
    buscar_horarios_turmas,
    buscar_info_associacao,
    buscar_precos,
    listar_modalidades,
)


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


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
    norm = _norm(user_message)
    parts: list[str] = []

    if any(token in norm for token in ("judo", "jui", "jiu")):
        parts.append(buscar_horarios_turmas("judo infantil"))
        parts.append(buscar_horarios_turmas("judo adulto"))
        if any(token in norm for token in ("preco", "preço", "valor", "mensalidade", "plano")):
            parts.append(buscar_precos("judo infantil"))
    elif "yoga" in norm:
        parts.append(buscar_horarios_turmas("yoga"))
        if any(token in norm for token in ("preco", "preço", "valor", "mensalidade", "plano")):
            parts.append(buscar_precos("yoga"))
    elif any(token in norm for token in ("preco", "preço", "valor", "mensalidade")):
        parts.append(buscar_precos(""))
    elif any(token in norm for token in ("endereco", "endereço", "onde", "local")):
        parts.append(buscar_info_associacao("endereço"))
    elif any(token in norm for token in ("modalidade", "atividade", "aula", "horario", "horário")):
        parts.append(listar_modalidades())
    else:
        faq = buscar_faq(user_message)
        if faq and "não encontrei" not in faq.lower() and not faq.strip().startswith("P:"):
            parts.append(faq)

    if not parts:
        listing = listar_modalidades()
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
        "oficiais da associação:\n\n"
    )
    outro = (
        "\n\nDigite *quero falar com a secretaria* se precisar de ajuda humana."
    )
    return f"{intro}{cleaned}{outro}"
