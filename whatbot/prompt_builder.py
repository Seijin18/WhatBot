"""Build LLM system prompts with association knowledge."""

from __future__ import annotations

import logging

from .knowledge import get_knowledge_store

logger = logging.getLogger("whatbot.prompt")


def build_enriched_system_prompt(system_prompt: str) -> str:
    """Inject knowledge Markdown summary into any LLM system prompt."""
    try:
        store = get_knowledge_store()
        base = store.get()
        parts = [
            system_prompt,
            "",
            "Base de conhecimento (use apenas estes dados):",
            store.listar_modalidades(),
        ]
        for key in (
            "sobre a associacao",
            "endereco e contato",
            "matricula e pagamentos",
            "precos",
        ):
            if key in base.secoes:
                parts.append(f"\n{key.title()}:\n{base.secoes[key]}")
        if base.faq:
            parts.append("\nFAQ:")
            for question, answer in base.faq.items():
                parts.append(f"- {question}: {answer}")
        return "\n".join(parts)
    except Exception as exc:
        logger.warning("Knowledge indisponivel no prompt: %s", exc)
        return system_prompt
