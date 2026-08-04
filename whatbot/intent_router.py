"""Lightweight intent routing from user messages, session context, and KB signals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Protocol

from .knowledge_facts import extract_days, get_knowledge_facts, norm_text
from .session_state import SessionState

class HistoryMessage(Protocol):
    direction: str
    text: str

INTENT_GREETING = "greeting"
INTENT_HORARIOS = "horarios"
INTENT_PRECOS = "precos"
INTENT_PAGAMENTO = "pagamento"
INTENT_ENTREGA = "entrega"
INTENT_EXPERIMENTAL = "experimental"
INTENT_MATRICULA = "matricula"
INTENT_FAQ = "faq"
INTENT_UNKNOWN = "unknown"

_FOLLOW_UP_VERBS = frozenset({"quero", "prefiro", "gostaria", "pode ser"})
_LISTING_SIGNALS = frozenset(
    {"modalidade", "modalidades", "atividades", "o que voces tem", "o que oferece"}
)
_INTENT_PRIORITY = (
    INTENT_EXPERIMENTAL,
    INTENT_PRECOS,
    INTENT_PAGAMENTO,
    INTENT_ENTREGA,
    INTENT_MATRICULA,
    INTENT_HORARIOS,
    INTENT_FAQ,
    INTENT_GREETING,
)


def _best_intent(scores: dict[str, int]) -> str | None:
    if not scores:
        return None
    best = max(scores.values())
    if best < 1:
        return None
    for intent_name in _INTENT_PRIORITY:
        if scores.get(intent_name, 0) == best:
            return intent_name
    return None


@dataclass
class IntentResult:
    intent: str
    confidence: str = "keyword"
    modalities: List[str] | None = None


def high_risk_intents() -> frozenset[str]:
    """Intents that should use template replies instead of free-form LLM output."""
    return get_knowledge_facts().high_risk_intents


def route_intent(
    user_message: str,
    session: SessionState | None = None,
    history: Optional[List[HistoryMessage]] = None,
) -> IntentResult:
    facts = get_knowledge_facts()
    norm = norm_text(user_message)
    session = session or SessionState()
    modalities = facts.resolve_modalidades(user_message, session.modalidade_interesse)

    greeting_signals = facts.intent_signals.get(INTENT_GREETING, set())
    if len(norm.split()) <= 4 and any(token in norm for token in greeting_signals):
        return IntentResult(INTENT_GREETING, modalities=modalities)

    if session.topico_atual == INTENT_EXPERIMENTAL or session.aguardando_dados_experimental:
        if extract_days(user_message) or re.search(r"\b\d{1,2}h", norm):
            return IntentResult(INTENT_EXPERIMENTAL, modalities=modalities)

    if extract_days(user_message) and any(token in norm for token in _FOLLOW_UP_VERBS):
        if session.modalidade_interesse or session.topico_atual in {
            INTENT_EXPERIMENTAL,
            INTENT_PRECOS,
            INTENT_HORARIOS,
        }:
            return IntentResult(INTENT_EXPERIMENTAL, modalities=modalities)

    if any(token in norm for token in _LISTING_SIGNALS):
        return IntentResult(INTENT_HORARIOS, modalities=modalities)

    scores = facts.score_intents(user_message)
    if session.topico_atual == INTENT_PRECOS:
        scores[INTENT_PRECOS] = scores.get(INTENT_PRECOS, 0) + 2

    chosen = _best_intent(scores)
    if chosen and chosen != INTENT_GREETING:
        return IntentResult(chosen, modalities=modalities)

    if session.topico_atual == INTENT_PRECOS and len(norm.split()) <= 6:
        if modalities or session.modalidade_interesse:
            return IntentResult(
                INTENT_PRECOS,
                modalities=modalities or session.modalidade_interesse,
            )

    if modalities:
        if scores.get(INTENT_HORARIOS, 0) > 0 or any(
            token in norm for token in facts.intent_signals.get(INTENT_HORARIOS, set())
        ):
            return IntentResult(INTENT_HORARIOS, modalities=modalities)
        return IntentResult(INTENT_FAQ, modalities=modalities)

    return IntentResult(INTENT_UNKNOWN, modalities=modalities)
