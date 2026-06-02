"""Build LLM system prompts with association knowledge."""

from __future__ import annotations

import logging

from .intent_router import (
    INTENT_EXPERIMENTAL,
    INTENT_FAQ,
    INTENT_HORARIOS,
    INTENT_MATRICULA,
    INTENT_PRECOS,
    IntentResult,
)
from .knowledge import get_knowledge_store
from .session_state import SessionState

logger = logging.getLogger("whatbot.prompt")


def _chunks_for_intent(intent: IntentResult, session: SessionState) -> list[str]:
    store = get_knowledge_store()
    base = store.get()
    chunks: list[str] = []

    intent_name = intent.intent
    if intent_name in {INTENT_HORARIOS, INTENT_EXPERIMENTAL, INTENT_PRECOS, INTENT_MATRICULA}:
        sobre = base.secoes.get("sobre a associacao")
        if sobre:
            chunks.append(f"Sobre:\n{sobre}")

    if intent_name == INTENT_HORARIOS:
        mods = intent.modalities or session.modalidade_interesse
        if mods:
            for mod in mods:
                item = store._match_modalidade(mod)
                if item:
                    chunks.append(item.as_text())
        else:
            for item in list(base.modalidades.values())[:2]:
                chunks.append(item.as_text())

    elif intent_name == INTENT_PRECOS:
        precos = base.secoes.get("precos")
        if precos:
            chunks.append(f"Preços:\n{precos}")
        matricula = base.secoes.get("matricula e pagamentos")
        if matricula:
            chunks.append(f"Matrícula e pagamentos:\n{matricula}")

    elif intent_name == INTENT_EXPERIMENTAL or intent_name == INTENT_MATRICULA:
        matricula = base.secoes.get("matricula e pagamentos")
        if matricula:
            chunks.append(f"Matrícula e pagamentos:\n{matricula}")
        faq_key = None
        for key in base.faq:
            if "experimental" in key:
                faq_key = key
                break
        if faq_key:
            chunks.append(f"FAQ:\n{faq_key}: {base.faq[faq_key]}")

    elif intent_name == INTENT_FAQ:
        chunks.append(store.format_full_context_for_prompt()[:2500])

    else:
        listing = store.listar_modalidades()
        sobre = base.secoes.get("sobre a associacao")
        if sobre:
            chunks.append(f"Sobre:\n{sobre}")
        if listing:
            chunks.append(listing)

    return chunks[:3]


def build_context_for_intent(
    intent: IntentResult,
    session: SessionState | None = None,
) -> str:
    """Return 1–3 knowledge chunks relevant to the detected intent."""
    session = session or SessionState()
    chunks = _chunks_for_intent(intent, session)
    if not chunks:
        return get_knowledge_store().format_full_context_for_prompt()
    return "\n\n".join(chunks)


def build_enriched_system_prompt(
    system_prompt: str,
    intent: IntentResult | None = None,
    session: SessionState | None = None,
    history_summary: str = "",
) -> str:
    """Inject targeted knowledge chunks into the LLM system prompt."""
    try:
        store = get_knowledge_store()
        if intent is None:
            from .intent_router import route_intent

            intent = route_intent("", session or SessionState())
        context = build_context_for_intent(intent, session)
        parts = [
            system_prompt,
            store.format_grounding_rules_for_prompt(),
            "",
            "=== BASE DE CONHECIMENTO (única fonte permitida) ===",
            context,
            "=== FIM DA BASE ===",
        ]
        if history_summary:
            parts.extend(["", history_summary])
        return "\n".join(parts)
    except Exception as exc:
        logger.warning("Knowledge indisponivel no prompt: %s", exc)
        return system_prompt
