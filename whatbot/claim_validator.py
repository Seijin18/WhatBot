"""Deterministic validation of factual claims in bot replies."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from .knowledge_facts import (
    KnowledgeFacts,
    day_label,
    extract_days,
    extract_money_values,
    get_knowledge_facts,
    norm_text,
)
from .session_state import SessionState

def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"[.!?\n]+", text) if s.strip()]


def _strip_boilerplate(text: str) -> str:
    norm = norm_text(text)
    marker = "se quiser agendar aula experimental"
    idx = norm.find(marker)
    if idx >= 0:
        return text[: len(text) - (len(norm) - idx)].strip()
    return text


_SCHEDULE_EXPERIMENTAL = re.compile(
    r"experimental[^.\n]{0,80}\b(na|no)\s+"
    r"(segunda(?:-feira)?|tercas?(?:-feira)?|quartas?(?:-feira)?|"
    r"quintas?(?:-feira)?|sextas?(?:-feira)?|sabados?|domingos?)",
    re.I,
)


def _schedules_experimental_on_day(text: str) -> bool:
    return bool(_SCHEDULE_EXPERIMENTAL.search(text))


def _claims_experimental_price(text: str) -> bool:
    for sentence in _split_sentences(text):
        sn = norm_text(sentence)
        if "experimental" in sn and extract_money_values(sentence):
            return True
    return False


def _is_price_table(text: str) -> bool:
    norm = norm_text(text)
    return "tabela de precos" in norm or norm.count("r$") >= 2


def _infer_modalities(text: str, session: SessionState, facts: KnowledgeFacts) -> List[str]:
    mods = facts.match_modalidades(text)
    if not mods and session.modalidade_interesse:
        mods = list(session.modalidade_interesse)
    if not mods and facts.experimental_slots:
        mods = [facts.experimental_slots[0].primary_name()]
    return mods


@dataclass
class ValidationResult:
    valid: bool
    violations: List[str] = field(default_factory=list)
    violation_codes: List[str] = field(default_factory=list)


class ClaimValidator:
    def __init__(self, facts: KnowledgeFacts | None = None):
        self._facts = facts or get_knowledge_facts()

    def validate(
        self,
        reply: str,
        user_message: str = "",
        session: SessionState | None = None,
    ) -> ValidationResult:
        session = session or SessionState()
        violations: list[str] = []
        codes: list[str] = []
        body = _strip_boilerplate(reply)
        reply_norm = norm_text(body)

        if _schedules_experimental_on_day(body):
            for sentence in _split_sentences(body):
                if not _schedules_experimental_on_day(sentence):
                    continue
                days = extract_days(sentence)
                modalities = _infer_modalities(f"{sentence} {user_message}", session, self._facts)
                for mod in modalities:
                    allowed = self._facts.experimental_days_for(mod)
                    if not allowed:
                        continue
                    for day in days:
                        if day in allowed:
                            continue
                        allowed_label = ", ".join(day_label(d) for d in allowed)
                        violations.append(
                            f"Aula experimental de {mod}: dia "
                            f"{day_label(day)} não permitido (apenas {allowed_label})"
                        )
                        codes.append("experimental_wrong_day")

        if _claims_experimental_price(body):
            violations.append(
                "A base não define preço de aula experimental — não cite valores"
            )
            codes.append("experimental_price_forbidden")

        money = extract_money_values(body)
        monthly = self._facts.monthly_price
        if money and monthly and monthly in money and not _is_price_table(body):
            has_plan_context = any(
                t in reply_norm
                for t in ("mensal", "semestral", "plano", "tabela", "modalidade")
            )
            if _claims_experimental_price(body):
                violations.append(
                    f"R$ {monthly} refere-se ao plano mensal, não à aula experimental"
                )
                codes.append("monthly_price_as_experimental")
            elif not has_plan_context and len(body) < 400:
                violations.append(
                    f"R$ {monthly} deve ser apresentado como plano mensal ou semestral"
                )
                codes.append("price_missing_plan_context")

        return ValidationResult(
            valid=len(violations) == 0,
            violations=violations,
            violation_codes=codes,
        )


def get_claim_validator() -> ClaimValidator:
    return ClaimValidator()
