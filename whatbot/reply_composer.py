"""Intent-aware reply composition from the knowledge base (no LLM dumps)."""

from __future__ import annotations

from typing import List, Optional

from .intent_router import (
    INTENT_EXPERIMENTAL,
    INTENT_FAQ,
    INTENT_GREETING,
    INTENT_HORARIOS,
    INTENT_MATRICULA,
    INTENT_PRECOS,
    INTENT_UNKNOWN,
    IntentResult,
    _LISTING_SIGNALS,
)
from .knowledge_facts import KnowledgeFacts, day_label, extract_days, get_knowledge_facts, norm_text
from .session_state import SessionState
from .tools import buscar_faq, buscar_horarios_turmas, buscar_info_associacao, buscar_precos

_CLOSING = (
    "Se quiser agendar aula experimental ou falar com a secretaria, é só me avisar."
)


class ReplyComposer:
    def __init__(self, facts: KnowledgeFacts | None = None):
        self._facts = facts or get_knowledge_facts()

    def compose(
        self,
        intent_result: IntentResult,
        user_message: str,
        session: SessionState | None = None,
        violation_codes: Optional[List[str]] = None,
    ) -> str | None:
        session = session or SessionState()
        intent = intent_result.intent
        codes = set(violation_codes or [])

        if codes & {"experimental_wrong_day", "experimental_price_forbidden", "monthly_price_as_experimental"}:
            return self._compose_experimental(user_message, session, intent_result)

        handlers = {
            INTENT_GREETING: self._compose_greeting,
            INTENT_HORARIOS: self._compose_horarios,
            INTENT_PRECOS: self._compose_precos,
            INTENT_EXPERIMENTAL: self._compose_experimental,
            INTENT_MATRICULA: self._compose_matricula,
            INTENT_FAQ: self._compose_faq,
            INTENT_UNKNOWN: self._compose_faq,
        }
        handler = handlers.get(intent, self._compose_faq)
        return handler(user_message, session, intent_result)

    def _modality_families(self, mods: List[str]) -> List[str]:
        families: list[str] = []
        for mod in mods:
            root = mod.split("(")[0].strip() if "(" in mod else mod
            root = root.split()[0] if root.split() else mod
            if not any(
                norm_text(root) in norm_text(existing) or norm_text(existing) in norm_text(root)
                for existing in families
            ):
                families.append(root)
        return families

    def _join_families(self, families: List[str]) -> str:
        if len(families) == 1:
            return families[0]
        return " e ".join(families[:-1]) + f" e {families[-1]}"

    def _modalities_label(self, mods: List[str], user_message: str = "") -> str:
        if user_message:
            asked = self._modality_families(self._facts.match_modalidades(user_message))
            if asked:
                return self._join_families(asked)
        if not mods:
            return "as modalidades cadastradas"
        families = self._modality_families(mods)
        all_families = self._modality_families(self._facts.modalidade_names)
        if len(families) >= len(all_families):
            return "todas as modalidades cadastradas"
        return self._join_families(families)

    def _price_disclaimer(self) -> str:
        parts: list[str] = []
        if self._facts.monthly_price is not None:
            parts.append(f"plano mensal (R$ {self._facts.monthly_price})")
        if self._facts.semester_price is not None:
            parts.append(f"plano semestral (R$ {self._facts.semester_price})")
        if parts:
            joined = " e ".join(parts)
            return (
                f"Não há valor de experimental na nossa base — {joined} "
                "referem-se às aulas regulares."
            )
        return "Não há valor de experimental na nossa base."

    def _compose_greeting(
        self, user_message: str, session: SessionState, intent: IntentResult
    ) -> str:
        label = self._facts.association_name
        mods = ", ".join(self._facts.modalidade_names) or "nossas modalidades"
        return (
            f"Boa noite! Somos a {label}. "
            f"Temos {mods}. "
            f"Posso ajudar com horários, preços ou agendamento de aula experimental?"
        )

    def _compose_horarios(
        self, user_message: str, session: SessionState, intent: IntentResult
    ) -> str:
        norm = norm_text(user_message)
        if any(token in norm for token in _LISTING_SIGNALS):
            from .tools import listar_modalidades

            listing = listar_modalidades()
            return f"{listing}\n\n{_CLOSING}"

        mods = intent.modalities or session.modalidade_interesse or self._facts.modalidade_names
        parts: list[str] = []
        for mod in mods:
            block = buscar_horarios_turmas(mod)
            if block and "não encontrada" not in block.lower():
                parts.append(block)
        body = "\n".join(parts) or buscar_horarios_turmas(mods[0] if mods else "")
        return f"{body}\n\n{_CLOSING}"

    def _compose_precos(
        self, user_message: str, session: SessionState, intent: IntentResult
    ) -> str:
        mods = intent.modalities or session.modalidade_interesse
        if not mods:
            mods = self._facts.resolve_modalidades(user_message, session.modalidade_interesse)

        unique_groups = self._group_modalidades_for_pricing(mods)
        scope_mods = self._facts.resolve_modalidades(user_message, session.modalidade_interesse) or mods
        if len(unique_groups) >= 2 or len(self._modality_families(scope_mods)) >= 2:
            lines = [
                f"Os planos mensal e semestral valem para {self._modalities_label(scope_mods, user_message)}:",
                f"- Plano mensal: R$ {self._facts.monthly_price} (1 aluno)"
                if self._facts.monthly_price is not None
                else "- Plano mensal: consulte a secretaria",
                f"- Plano semestral: R$ {self._facts.semester_price} (1 aluno)"
                if self._facts.semester_price is not None
                else "- Plano semestral: consulte a secretaria",
                "Há desconto para o 2º integrante da mesma família — consulte a secretaria.",
                "Esses valores são dos planos regulares; a base não informa preço de aula experimental.",
            ]
            return "\n".join(lines) + f"\n\n{_CLOSING}"

        if unique_groups:
            body = buscar_precos(unique_groups[0])
        else:
            body = buscar_precos("")
        return f"{body}\n\n{_CLOSING}"

    def _group_modalidades_for_pricing(self, mods: List[str]) -> List[str]:
        """Collapse variant names (e.g. judô infantil/adulto) to one entry per family."""
        if not mods:
            return []
        groups: list[str] = []
        for mod in mods:
            root = mod.split()[0] if mod.split() else mod
            if not any(root in existing or existing in mod for existing in groups):
                groups.append(mod)
        return groups

    def _compose_experimental(
        self, user_message: str, session: SessionState, intent: IntentResult
    ) -> str:
        norm = norm_text(user_message)
        requested = extract_days(user_message)
        requested_day = requested[0] if requested else None
        slots = self._facts.experimental_slots

        if "mais de uma" in norm or "quantas" in norm:
            lines = [
                "Sim, você pode agendar aula experimental — cada modalidade tem seu dia disponível:"
            ]
            for slot in slots:
                day = day_label(slot.days[0]) if slot.days else "consulte a secretaria"
                lines.append(f"- {slot.primary_name()}: {day}")
            lines.extend(
                [
                    "",
                    "Para agendar, envie nome, idade, celular/telefone e o dia desejado.",
                    "",
                    _CLOSING,
                ]
            )
            return "\n".join(lines)

        primary = self._facts.primary_modalidade(
            user_message, session.modalidade_interesse
        )
        if not primary and slots:
            primary = slots[0].primary_name()

        if requested_day and primary:
            allowed = self._facts.experimental_days_for(primary)
            if allowed and requested_day not in allowed:
                allowed_label = day_label(allowed[0])
                return (
                    f"Para aula experimental de {primary}, o dia disponível é {allowed_label}. "
                    f"As aulas regulares de {primary} também ocorrem em outros dias da semana, "
                    f"mas a experimental é só nesse dia.\n\n"
                    "Para agendar, envie nome, idade, celular/telefone e confirme o dia.\n\n"
                    f"{_CLOSING}"
                )

        slot = self._facts.experimental_slot_for(primary) if primary else None
        day_text = day_label(slot.days[0]) if slot and slot.days else "consulte a secretaria"
        modality_label = primary or (slot.primary_name() if slot else "a modalidade")

        return (
            f"A aula experimental de {modality_label} é agendada para {day_text}. "
            f"{self._price_disclaimer()}\n\n"
            "Para agendar, envie nome, idade, celular/telefone e o dia desejado.\n\n"
            f"{_CLOSING}"
        )

    def _compose_matricula(
        self, user_message: str, session: SessionState, intent: IntentResult
    ) -> str:
        info = buscar_info_associacao("matrícula")
        return f"{info}\n\n{_CLOSING}"

    def _compose_faq(
        self, user_message: str, session: SessionState, intent: IntentResult
    ) -> str | None:
        norm = norm_text(user_message)
        faq_signals = self._facts.intent_signals.get(INTENT_FAQ, set())
        if any(token in norm for token in faq_signals if token in {"quem", "sobre", "associacao", "nome"}):
            info = buscar_info_associacao("sobre a associação")
            if info and "não encontrei" not in info.lower():
                body = info.replace("Sobre a associação:", "").replace("Sobre:", "").strip()
                return f"{body}\n\n{_CLOSING}"

        faq = buscar_faq(user_message)
        if faq and "não encontrei" not in faq.lower():
            cleaned = faq.replace("P:", "").replace("R:", "").strip()
            if len(cleaned) < 800:
                return f"{cleaned}\n\n{_CLOSING}"
        return None


def get_reply_composer() -> ReplyComposer:
    return ReplyComposer()
