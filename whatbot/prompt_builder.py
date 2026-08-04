"""Build LLM system prompts with business knowledge."""

from __future__ import annotations

import logging

from .intent_router import IntentResult
from .knowledge import get_knowledge_store
from .session_state import SessionState

logger = logging.getLogger("whatbot.prompt")


def build_context_for_intent(
    intent: IntentResult | None = None,
    session: SessionState | None = None,
) -> str:
    """Return the full knowledge context for the LLM prompt.

    Always returns the complete knowledge base rather than an intent-based
    slice: a per-intent excerpt only makes sense once the base is too large
    to fit a prompt, and picking the slice by hand-mapped intent name (e.g.
    "precos" -> seção "Preços") silently drops sections whenever the
    knowledge file's structure doesn't match that hardcoded map — which is
    exactly what happened when the KB changed from a class-schedule business
    to a made-to-order product catalog (see docs/REVISAO_CAMADA_CONVERSACIONAL.md,
    P0.1: greeting/unknown intents got no catalog, no prices, no FAQ at all).
    `intent`/`session` are accepted for call-site compatibility but unused.
    """
    del intent, session
    return get_knowledge_store().format_full_context_for_prompt()


def build_enriched_system_prompt(
    system_prompt: str,
    intent: IntentResult | None = None,
    session: SessionState | None = None,
    history_summary: str = "",
) -> str:
    """Inject the full knowledge base into the LLM system prompt."""
    try:
        store = get_knowledge_store()
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
