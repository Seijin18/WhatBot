"""Experimental booking funnel — state machine (LangGraph-ready, no extra deps).

LangGraph evaluation (plan phase 3):
- Current: deterministic states in this module, invoked from ReplyComposer / main.
- Future: same states as LangGraph nodes (collect_name → collect_age → collect_phone → confirm_day).
- Qdrant not needed: all facts fit in structured KB from associacao.md.

States:
  idle → awaiting_experimental_data → ready_for_handover
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BookingState(str, Enum):
    IDLE = "idle"
    AWAITING_EXPERIMENTAL_DATA = "awaiting_experimental_data"
    READY_FOR_HANDOVER = "ready_for_handover"


@dataclass
class BookingFlow:
    state: BookingState = BookingState.IDLE
    nome: str | None = None
    idade: str | None = None
    telefone: str | None = None
    dia: str | None = None
    modalidade: str | None = None

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.nome:
            missing.append("nome")
        if not self.idade:
            missing.append("idade")
        if not self.telefone:
            missing.append("celular/telefone")
        if not self.dia:
            missing.append("dia desejado")
        return missing

    def prompt_for_missing(self) -> str:
        fields = ", ".join(self.missing_fields())
        return (
            f"Para concluir o agendamento da aula experimental, ainda preciso: {fields}."
        )


def next_booking_state(current: BookingState, has_all_data: bool) -> BookingState:
    if current == BookingState.IDLE:
        return BookingState.AWAITING_EXPERIMENTAL_DATA
    if has_all_data:
        return BookingState.READY_FOR_HANDOVER
    return BookingState.AWAITING_EXPERIMENTAL_DATA
