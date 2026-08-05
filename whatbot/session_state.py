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


@dataclass
class SessionState:
    item_interesse: List[str] = field(default_factory=list)
    topico_atual: str | None = None
    aguardando_dados_experimental: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SessionState:
        if not data:
            return cls()
        return cls(
            item_interesse=list(data.get("item_interesse") or []),
            topico_atual=data.get("topico_atual"),
            aguardando_dados_experimental=bool(
                data.get("aguardando_dados_experimental", False)
            ),
        )

    def primary_item(self) -> str | None:
        return self.item_interesse[0] if self.item_interesse else None


def update_session_state(
    state: SessionState,
    intent: str,
    items: Optional[List[str]] = None,
) -> SessionState:
    """Refresh session fields from the intent/items already resolved by
    `route_intent` for the current turn.

    Deliberately does NOT recompute items from `user_message`/`history` on
    its own — that used to call `KnowledgeFacts.match_items` (then still
    named `match_modalidades`) a second time, independently of
    `route_intent`, with its own fallback that scanned the last 6 history
    messages. Both heuristics ran on the same turn and could disagree about
    what the customer showed interest in; the caller (`whatbot/main.py`)
    now passes the single `IntentResult` already computed by `route_intent`
    instead.
    """
    if items:
        state.item_interesse = list(dict.fromkeys(items))
    state.topico_atual = intent
    if intent == "experimental":
        state.aguardando_dados_experimental = True
    elif intent in {"precos", "pagamento", "entrega", "pedido", "horarios", "greeting", "faq"}:
        state.aguardando_dados_experimental = False
    return state


# Business stages that a contact only ever reaches via manual admin action
# (`whatbot/admin.py`), never automatically from a customer turn.
_MANUAL_ONLY_STATUSES = {"cliente_ativo", "cancelado"}


def next_status(
    current_status: str,
    session: SessionState,
    intent: str,
    has_order: bool = False,
) -> str | None:
    """Compute the contact's next business stage (`contatos.status`) from
    this turn's already-resolved session/intent, or `None` when no
    transition applies.

    Rules (contact-interest-memory):
    - `novo_lead` -> `interessado` once `session.item_interesse` is no
      longer empty.
    - -> `comprando` when `intent == INTENT_PEDIDO` (the customer states
      purchase intent in text) or `has_order` is `True` (a real catalog
      order arrived — `has_order` is always `False` today; it becomes
      meaningful once `catalog-order-capture` adds an `order` key to the
      inbound payload).
    - Never regresses: once `comprando`, a neutral follow-up message keeps
      the contact there.
    - `cliente_ativo` and `cancelado` are never reached automatically here —
      only through the admin's manual command (`whatbot/admin.py`) — and,
      once in either, this function stops proposing further automatic
      transitions.
    """
    # Deferred import: `intent_router` imports `SessionState` from this
    # module, so importing `INTENT_PEDIDO` at module level would be circular.
    from .intent_router import INTENT_PEDIDO

    if current_status in _MANUAL_ONLY_STATUSES or current_status == "comprando":
        return None

    if intent == INTENT_PEDIDO or has_order:
        return "comprando"

    if current_status == "novo_lead" and session.item_interesse:
        return "interessado"

    return None


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
        topics.extend(facts.match_items(record.text))
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
