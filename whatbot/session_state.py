"""Per-contact conversation state for grounding and follow-up context."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional, Protocol

from .knowledge_facts import get_knowledge_facts, norm_text

class HistoryMessage(Protocol):
    direction: str
    text: str


def _norm(text: str) -> str:
    return norm_text(text)


def detect_modalidades(text: str) -> List[str]:
    """Return modalidade names from the knowledge base mentioned in text."""
    return get_knowledge_facts().match_modalidades(text)


@dataclass
class SessionState:
    modalidade_interesse: List[str] = field(default_factory=list)
    topico_atual: str | None = None
    aguardando_dados_experimental: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SessionState:
        if not data:
            return cls()
        return cls(
            modalidade_interesse=list(data.get("modalidade_interesse") or []),
            topico_atual=data.get("topico_atual"),
            aguardando_dados_experimental=bool(
                data.get("aguardando_dados_experimental", False)
            ),
        )

    def primary_modalidade(self) -> str | None:
        return self.modalidade_interesse[0] if self.modalidade_interesse else None


def update_session_state(
    state: SessionState,
    user_message: str,
    intent: str,
    history: Optional[List[HistoryMessage]] = None,
) -> SessionState:
    """Refresh session fields from the latest user turn and recent history."""
    facts = get_knowledge_facts()
    modalities = facts.match_modalidades(user_message)
    if not modalities and history:
        for record in history[:6]:
            if record.direction == "in":
                modalities.extend(facts.match_modalidades(record.text))
    modalities = list(dict.fromkeys(modalities))

    if modalities:
        state.modalidade_interesse = modalities
    state.topico_atual = intent
    if intent == "experimental":
        state.aguardando_dados_experimental = True
    elif intent in {"precos", "pagamento", "entrega", "pedido", "horarios", "greeting", "faq"}:
        state.aguardando_dados_experimental = False
    return state


def history_summary(history: List[HistoryMessage], max_turns: int = 4) -> str:
    """One-line summary of recent topics for LLM context."""
    facts = get_knowledge_facts()
    topics: list[str] = []
    for record in history[:max_turns]:
        if record.direction != "in":
            continue
        norm = _norm(record.text)
        if any(token in norm for token in facts.intent_signals.get("precos", set())):
            topics.append("preços")
        if any(token in norm for token in facts.intent_signals.get("pagamento", set())):
            topics.append("pagamento")
        if any(token in norm for token in facts.intent_signals.get("entrega", set())):
            topics.append("entrega/prazo")
        if any(token in norm for token in facts.intent_signals.get("horarios", set())):
            topics.append("horários")
        if any(token in norm for token in facts.intent_signals.get("experimental", set())):
            topics.append("aula experimental")
        topics.extend(facts.match_modalidades(record.text))
    if not topics:
        return ""
    unique = list(dict.fromkeys(topics))
    return f"Contexto recente: cliente mencionou {', '.join(unique)}."


def parse_session_state(raw: str | dict | None) -> SessionState:
    if raw is None:
        return SessionState()
    if isinstance(raw, dict):
        return SessionState.from_dict(raw)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return SessionState.from_dict(data)
    except (json.JSONDecodeError, TypeError):
        pass
    return SessionState()
