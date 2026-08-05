"""Intent-aware reply composition from the knowledge base (no LLM dumps)."""

from __future__ import annotations

from typing import List, Optional

from .intent_router import (
    INTENT_EXPERIMENTAL,
    INTENT_FAQ,
    INTENT_GREETING,
    INTENT_HORARIOS,
    INTENT_PEDIDO,
    INTENT_PRECOS,
    INTENT_UNKNOWN,
    IntentResult,
    _LISTING_SIGNALS,
)
from .knowledge_facts import KnowledgeFacts, day_label, extract_days, get_knowledge_facts, norm_text
from .session_state import SessionState
from .tools import buscar_faq, buscar_horarios_turmas, buscar_info_negocio, buscar_precos

_GENERIC_CLOSING = "Se precisar de mais alguma coisa, é só me chamar."
_EXPERIMENTAL_CLOSING = (
    "Se quiser agendar aula experimental ou falar com a secretaria, é só me avisar."
)


def default_closing(facts: KnowledgeFacts) -> str:
    """Closing line adapted to whether this business offers trial classes."""
    if facts.experimental_slots:
        return _EXPERIMENTAL_CLOSING
    return _GENERIC_CLOSING


class ReplyComposer:
    def __init__(self, facts: KnowledgeFacts | None = None):
        self._facts = facts or get_knowledge_facts()

    def _closing(self) -> str:
        return default_closing(self._facts)

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
            INTENT_PEDIDO: self._compose_pedido,
            INTENT_FAQ: self._compose_faq,
            INTENT_UNKNOWN: self._compose_faq,
        }
        handler = handlers.get(intent, self._compose_faq)
        return handler(user_message, session, intent_result)

    def _item_families(self, items: List[str]) -> List[str]:
        families: list[str] = []
        for item in items:
            root = item.split("(")[0].strip() if "(" in item else item
            root = root.split()[0] if root.split() else item
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

    def _items_label(self, items: List[str], user_message: str = "") -> str:
        if user_message:
            asked = self._item_families(self._facts.match_items(user_message))
            if asked:
                return self._join_families(asked)
        if not items:
            return "os itens cadastrados"
        families = self._item_families(items)
        all_families = self._item_families(self._facts.item_names)
        if len(families) >= len(all_families):
            return "todos os itens cadastrados"
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
        label = self._facts.business_name
        if self._facts.item_names:
            items = ", ".join(self._facts.item_names)
            return (
                f"Olá! Somos a {label}. "
                f"Temos {items}. "
                f"Posso ajudar com horários, preços ou agendamento de aula experimental?"
            )
        return (
            f"Olá! Somos a {label}. "
            "Posso ajudar com informações sobre nossos produtos, preços ou como fazer um pedido?"
        )

    def _compose_horarios(
        self, user_message: str, session: SessionState, intent: IntentResult
    ) -> str:
        from .tools import listar_itens

        if not self._facts.item_names:
            # No `## Itens` section in this KB — there's no schedule to
            # look up, so the closest useful reply to a "horários"/"o que
            # vocês têm" style question is the catalog/price listing
            # (`listar_itens()` itself falls back to it — see
            # docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.1/P1.3). Without
            # this early return, the code below fell through to
            # `buscar_horarios_turmas("")`, which returned a broken
            # "Item '' não encontrado" message.
            return f"{listar_itens()}\n\n{self._closing()}"

        norm = norm_text(user_message)
        if any(token in norm for token in _LISTING_SIGNALS):
            listing = listar_itens()
            return f"{listing}\n\n{self._closing()}"

        items = intent.items or session.item_interesse or self._facts.item_names
        parts: list[str] = []
        for item in items:
            block = buscar_horarios_turmas(item)
            if block and "não encontrado" not in block.lower():
                parts.append(block)
        body = "\n".join(parts) or buscar_horarios_turmas(items[0] if items else "")
        return f"{body}\n\n{self._closing()}"

    def _compose_precos(
        self, user_message: str, session: SessionState, intent: IntentResult
    ) -> str:
        items = intent.items or session.item_interesse
        if not items:
            items = self._facts.resolve_items(user_message, session.item_interesse)

        unique_groups = self._group_items_for_pricing(items)
        scope_items = self._facts.resolve_items(user_message, session.item_interesse) or items
        if len(unique_groups) >= 2 or len(self._item_families(scope_items)) >= 2:
            lines = [
                f"Os planos mensal e semestral valem para {self._items_label(scope_items, user_message)}:",
                f"- Plano mensal: R$ {self._facts.monthly_price} (1 aluno)"
                if self._facts.monthly_price is not None
                else "- Plano mensal: consulte o atendimento",
                f"- Plano semestral: R$ {self._facts.semester_price} (1 aluno)"
                if self._facts.semester_price is not None
                else "- Plano semestral: consulte o atendimento",
                "Há desconto para o 2º integrante da mesma família — consulte o atendimento.",
                "Esses valores são dos planos regulares; a base não informa preço de aula experimental.",
            ]
            return "\n".join(lines) + f"\n\n{self._closing()}"

        if unique_groups:
            body = buscar_precos(unique_groups[0])
        else:
            body = buscar_precos("")
        return f"{body}\n\n{self._closing()}"

    def _group_items_for_pricing(self, items: List[str]) -> List[str]:
        """Collapse variant names (e.g. judô infantil/adulto) to one entry per family."""
        if not items:
            return []
        groups: list[str] = []
        for item in items:
            root = item.split()[0] if item.split() else item
            if not any(root in existing or existing in item for existing in groups):
                groups.append(item)
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
                "Sim, você pode agendar aula experimental — cada item tem seu dia disponível:"
            ]
            for slot in slots:
                day = day_label(slot.days[0]) if slot.days else "consulte o atendimento"
                lines.append(f"- {slot.primary_name()}: {day}")
            lines.extend(
                [
                    "",
                    "Para agendar, envie nome, idade, celular/telefone e o dia desejado.",
                    "",
                    self._closing(),
                ]
            )
            return "\n".join(lines)

        primary = self._facts.primary_item(
            user_message, session.item_interesse
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
                    f"{self._closing()}"
                )

        slot = self._facts.experimental_slot_for(primary) if primary else None
        day_text = day_label(slot.days[0]) if slot and slot.days else "consulte o atendimento"
        item_label = primary or (slot.primary_name() if slot else "o item")

        return (
            f"A aula experimental de {item_label} é agendada para {day_text}. "
            f"{self._price_disclaimer()}\n\n"
            "Para agendar, envie nome, idade, celular/telefone e o dia desejado.\n\n"
            f"{self._closing()}"
        )

    def _compose_pedido(
        self, user_message: str, session: SessionState, intent: IntentResult
    ) -> str:
        info = buscar_info_negocio("como comprar")
        return f"{info}\n\n{self._closing()}"

    def _compose_faq(
        self, user_message: str, session: SessionState, intent: IntentResult
    ) -> str | None:
        norm = norm_text(user_message)
        faq_signals = self._facts.intent_signals.get(INTENT_FAQ, set())
        if any(token in norm for token in faq_signals if token in {"quem", "sobre", "nome"}):
            info = buscar_info_negocio("sobre")
            if info and "não encontrei" not in info.lower():
                body = info.replace("Sobre:", "").strip()
                return f"{body}\n\n{self._closing()}"

        faq = buscar_faq(user_message)
        if faq and "não encontrei" not in faq.lower():
            cleaned = faq.replace("P:", "").replace("R:", "").strip()
            if len(cleaned) < 800:
                return f"{cleaned}\n\n{self._closing()}"
        return None


def get_reply_composer() -> ReplyComposer:
    return ReplyComposer()
