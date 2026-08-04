"""Structured facts and semantic helpers derived from the knowledge Markdown."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .knowledge import KnowledgeBase, get_knowledge_store

_DAY_ALIASES: Dict[str, str] = {
    "segunda": "segunda",
    "segundas": "segunda",
    "terca": "terca",
    "tercas": "terca",
    "quarta": "quarta",
    "quartas": "quarta",
    "quinta": "quinta",
    "quintas": "quinta",
    "sexta": "sexta",
    "sextas": "sexta",
    "sabado": "sabado",
    "sabados": "sabado",
    "domingo": "domingo",
    "domingos": "domingo",
}

_DAY_LABELS = {
    "segunda": "segunda-feira",
    "terca": "terça-feira",
    "quarta": "quarta-feira",
    "quinta": "quinta-feira",
    "sexta": "sexta-feira",
    "sabado": "sábado",
    "domingo": "domingo",
}

# Minimal conversational patterns not present as KB sections
_BASE_GREETING_SIGNALS = frozenset(
    {"ola", "oi", "bom dia", "boa tarde", "boa noite", "e ai", "e aí"}
)


def norm_text(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower().strip())


def extract_days(text: str) -> List[str]:
    n = norm_text(text)
    found: list[str] = []
    for alias, canonical in _DAY_ALIASES.items():
        if alias in n and canonical not in found:
            found.append(canonical)
    return found


def day_label(day: str) -> str:
    return _DAY_LABELS.get(day, day)


def extract_money_values(text: str) -> List[int]:
    values: list[int] = []
    for match in re.finditer(r"r\$\s*(\d+(?:[.,]\d+)?)", norm_text(text)):
        raw = match.group(1).replace(",", ".")
        try:
            values.append(int(float(raw)))
        except ValueError:
            continue
    return values


def match_items_in_text(text: str, base: KnowledgeBase) -> List[str]:
    """Return registered item names mentioned in text (longest match first)."""
    n = norm_text(text)
    hits: list[tuple[int, str]] = []
    for item in base.itens.values():
        name_norm = norm_text(item.nome)
        score = 0
        if name_norm in n:
            score += 5
        for token in name_norm.split():
            if len(token) < 3:
                continue
            if token in n:
                score += 2 if len(token) >= 5 else 1
        if score > 0:
            hits.append((score, item.nome))
    hits.sort(key=lambda x: (-x[0], x[1]))
    seen: set[str] = set()
    ordered: list[str] = []
    for _, name in hits:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _link_label_to_items(label: str, base: KnowledgeBase) -> List[str]:
    matched = match_items_in_text(label, base)
    if matched:
        return matched
    label_norm = norm_text(label)
    for item in base.itens.values():
        name_norm = norm_text(item.nome)
        label_tokens = [t for t in label_norm.split() if len(t) >= 4]
        name_tokens = [t for t in name_norm.split() if len(t) >= 4]
        if label_tokens and any(t in name_tokens or t in name_norm for t in label_tokens):
            matched.append(item.nome)
    return list(dict.fromkeys(matched)) or [label.strip()]


@dataclass
class ExperimentalSlot:
    """One experimental booking line from matrícula (e.g. judô → quinta)."""

    label: str
    days: List[str]
    itens: List[str]

    def primary_name(self) -> str:
        return self.itens[0] if self.itens else self.label


@dataclass
class KnowledgeFacts:
    """Canonical facts extracted from the knowledge base."""

    business_name: str
    item_names: List[str]
    experimental_slots: List[ExperimentalSlot] = field(default_factory=list)
    regular_days_by_item: Dict[str, List[str]] = field(default_factory=dict)
    monthly_price: Optional[int] = None
    semester_price: Optional[int] = None
    known_plan_prices: Set[int] = field(default_factory=set)
    intent_signals: Dict[str, Set[str]] = field(default_factory=dict)
    experimental_has_price: bool = False

    @property
    def high_risk_intents(self) -> frozenset[str]:
        risks: set[str] = set()
        if self.experimental_slots:
            risks.add("experimental")
        if self.monthly_price is not None or self.semester_price is not None:
            risks.add("precos")
        return frozenset(risks)

    def match_items(self, text: str) -> List[str]:
        from .knowledge import get_knowledge_store

        return match_items_in_text(text, get_knowledge_store().get())

    def experimental_days_for(self, item_ref: str) -> List[str]:
        ref = norm_text(item_ref)
        for slot in self.experimental_slots:
            if ref == norm_text(slot.label):
                return slot.days
            for name in slot.itens:
                if ref == norm_text(name) or ref in norm_text(name) or norm_text(name) in ref:
                    return slot.days
        for slot in self.experimental_slots:
            for name in slot.itens:
                if any(t in ref for t in norm_text(name).split() if len(t) >= 4):
                    return slot.days
        return []

    def resolve_items(
        self,
        text: str,
        session_items: Optional[List[str]] = None,
    ) -> List[str]:
        found = self.match_items(text)
        if session_items:
            for name in session_items:
                if name not in found:
                    found.append(name)
        return found

    def primary_item(
        self,
        text: str,
        session_items: Optional[List[str]] = None,
    ) -> Optional[str]:
        items = self.resolve_items(text, session_items)
        return items[0] if items else None

    def experimental_slot_for(self, item_ref: str) -> Optional[ExperimentalSlot]:
        ref = norm_text(item_ref)
        for slot in self.experimental_slots:
            if ref == norm_text(slot.label):
                return slot
            for name in slot.itens:
                if ref == norm_text(name) or ref in norm_text(name):
                    return slot
        return None

    def score_intents(self, text: str) -> Dict[str, int]:
        n = norm_text(text)
        scores: Dict[str, int] = {}
        for intent, tokens in self.intent_signals.items():
            score = sum(1 for token in tokens if token in n)
            if score:
                scores[intent] = score
        return scores


def _parse_experimental_slots(como_comprar_text: str, base: KnowledgeBase) -> List[ExperimentalSlot]:
    slots: list[ExperimentalSlot] = []
    for line in como_comprar_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        body = stripped[2:]
        match = re.search(
            r"aula experimental de\s+([^:]+):\s*(.+)",
            body,
            re.I,
        )
        if not match:
            continue
        label = match.group(1).strip()
        days = extract_days(match.group(2))
        if not days:
            continue
        slots.append(
            ExperimentalSlot(
                label=label,
                days=days,
                itens=_link_label_to_items(label, base),
            )
        )
    return slots


def _parse_regular_days(base: KnowledgeBase) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for item in base.itens.values():
        freq = item.campos.get("Frequência", "")
        horarios = item.campos.get("Horários", "")
        days = extract_days(f"{freq} {horarios}")
        if days:
            result[item.nome] = days
    for question, answer in base.faq.items():
        qn = norm_text(question)
        if "dia" not in qn and "horario" not in qn:
            continue
        days = extract_days(answer)
        if not days:
            continue
        linked = match_items_in_text(f"{question} {answer}", base)
        if linked:
            for name in linked:
                result.setdefault(name, days)
        else:
            result.setdefault(question, days)
    return result


def _parse_prices(base: KnowledgeBase) -> tuple[Optional[int], Optional[int], Set[int]]:
    monthly: Optional[int] = None
    semester: Optional[int] = None
    known: set[int] = set()
    for item in base.itens.values():
        for key, value in item.campos.items():
            kn = norm_text(key)
            vals = extract_money_values(value)
            if not vals:
                continue
            known.update(vals)
            if "mensal" in kn and monthly is None:
                monthly = vals[0]
            if "semestral" in kn and semester is None:
                semester = vals[0]
    if monthly is None or semester is None:
        precos = base.secoes.get("precos", "")
        precos_norm = norm_text(precos)
        vals = extract_money_values(precos)
        known.update(vals)
        # Only treat the first/second R$ values as "monthly"/"semester" plan
        # prices when the section actually talks about plans in those terms —
        # a plain price-per-item catalog (e.g. a product list) has no such
        # concept, and blindly taking vals[0]/vals[1] mislabels arbitrary
        # item prices, which then forces every price reply through the rigid
        # template path instead of a normal LLM answer.
        if vals and monthly is None and "mensal" in precos_norm:
            monthly = vals[0]
        if vals and semester is None and "semestral" in precos_norm and len(vals) > 1:
            semester = vals[1]
    return monthly, semester, known


def _tokens_from_bullets(text: str, min_len: int = 4) -> Set[str]:
    tokens: set[str] = set()
    for line in text.splitlines():
        line = line.strip().lstrip("- ").strip()
        for word in re.findall(r"[a-zà-ú]{3,}", norm_text(line)):
            if len(word) >= min_len:
                tokens.add(word)
    return tokens


# Small, curated, business-agnostic trigger vocabulary — seeded regardless
# of KB content because these are simply the words a Portuguese-speaking
# customer types for these intents in any small business. The previous
# design instead dumped every word from whatever KB section/FAQ answer
# happened to match as a "signal" for that intent, which meant e.g. a
# product catalog written as bullet points under "Preços" turned words like
# "correios", "prazo" and "conforme" into permanent triggers for the
# `precos` intent — almost any message scored as pricing (see
# docs/REVISAO_CAMADA_CONVERSACIONAL.md, P0.3).
_BASE_INTENT_SIGNALS: Dict[str, Set[str]] = {
    "precos": {
        "preco", "preço", "precos", "preços", "valor", "valores", "custa",
        "quanto custa", "quanto e", "quanto fica", "mensalidade", "plano", "planos",
    },
    "pagamento": {
        "pagamento", "pagamentos", "pagar", "pago", "pix", "cartao", "cartão",
        "parcelar", "parcelamento", "boleto", "forma de pagamento",
    },
    "entrega": {
        "entrega", "entregas", "entregar", "prazo", "demora", "correios",
        "frete", "envio", "enviar", "retirada", "retirar",
    },
    "pedido": {
        "matricula", "matrícula", "inscrever", "inscricao", "inscrição",
        "cadastrar", "encomendar", "encomenda", "pedido", "comprar",
    },
    "horarios": {
        "horario", "horário", "horarios", "horários", "que horas",
        # "modalidade"/"modalidades" are business-vocabulary trigger words:
        # a customer of a class-schedule business (e.g. a sports academy)
        # types these literal Portuguese words to ask "what do you have?" —
        # kept as content even though the internal schema/identifier this
        # code uses for a registered offering is `Item`, not `Modalidade`
        # (see tests/test_no_modalidade_leftovers.py).
        "modalidade", "modalidades", "atividades", "o que voces tem",
        "o que oferece",
    },
}

# Generic question/pronoun words that show up in almost every FAQ question
# regardless of topic — filtered out of tokens mined from FAQ questions (see
# `_build_intent_signals` below) so they don't become accidental cross-intent
# triggers.
_GENERIC_QUESTION_WORDS = frozenset(
    {
        "que", "quem", "qual", "quais", "quanto", "quando", "como", "onde",
        "para", "por", "com", "sem", "uma", "um", "umas", "uns", "dos", "das",
        "meu", "minha", "meus", "minhas", "seu", "sua", "seus", "suas",
        "ele", "ela", "eles", "elas", "isso", "essa", "esse", "essas", "esses",
        "voces", "vcs", "tem", "sao", "esta", "estao", "pode", "podem",
        "fazer", "ficar", "pronto", "outro", "outros", "outra", "outras",
    }
)


def _build_intent_signals(base: KnowledgeBase) -> Dict[str, Set[str]]:
    signals: Dict[str, Set[str]] = defaultdict(set)
    signals["greeting"].update(_BASE_GREETING_SIGNALS)
    for intent, tokens in _BASE_INTENT_SIGNALS.items():
        signals[intent].update(tokens)

    for item in base.itens.values():
        for key in item.campos:
            kn = norm_text(key)
            if any(t in kn for t in ("preco", "mensal", "semestral", "valor")):
                signals["precos"].add(kn)
            if any(t in kn for t in ("horario", "frequencia")):
                signals["horarios"].add(kn)

    como_comprar = base.secoes.get("como comprar e pagamento", "")
    if "experimental" in norm_text(como_comprar):
        signals["experimental"].update(
            {"experimental", "experimentar", "aula experimental"}
        )
        # Item names (e.g. "judô", "yoga") are excluded from the tokens
        # mined below: they show up on the same bullet line as
        # "experimental" (e.g. "Aula experimental: disponível para judô e
        # yoga...") purely because that's where the KB documents which
        # itens offer a trial, not because the name itself signals "I want
        # to book a trial" — a plain pricing question like "quanto custa o
        # judô?" would otherwise also nudge toward `experimental` (same
        # class of bug as P0.3, just in this section instead of Preços —
        # docs/REVISAO_CAMADA_CONVERSACIONAL.md).
        item_name_tokens = {
            tok
            for item in base.itens.values()
            for tok in re.findall(r"[a-z]+", norm_text(item.nome))
        }
        for line in como_comprar.splitlines():
            if "experimental" in norm_text(line):
                line_tokens = (
                    _tokens_from_bullets(line)
                    - _GENERIC_QUESTION_WORDS
                    - item_name_tokens
                )
                signals["experimental"].update(line_tokens)

    # FAQ *questions* are short, on-topic phrasings of how a customer
    # actually asks — safe to mine for extra tokens. FAQ *answers* are
    # prose and are deliberately NOT scanned: that was the other half of
    # the P0.3 bug (any word in a matched answer became a permanent
    # trigger for that intent). Generic question/pronoun words (quanto,
    # meu, para, ...) are stripped from the harvested tokens: unlike the
    # gate check just below (which only decides *whether* this question is
    # relevant to an intent), a leftover filler word becomes a standing
    # trigger for that intent in *every future message* — e.g. "meu" from
    # "Quanto custa uma miniatura do MEU pet?" would otherwise flag
    # "meu cachorro é um golden, dá pra fazer?" as a pricing question.
    for question in base.faq:
        qn = norm_text(question)
        q_tokens = _tokens_from_bullets(question, 3) - _GENERIC_QUESTION_WORDS
        if any(t in qn for t in ("preco", "custo", "custa", "valor")):
            signals["precos"].update(q_tokens)
        if any(t in qn for t in ("pagar", "pagamento", "pix", "cartao", "boleto")):
            signals["pagamento"].update(q_tokens)
        if any(t in qn for t in ("entrega", "prazo", "demora", "envio", "frete", "correios")):
            signals["entrega"].update(q_tokens)
        if any(t in qn for t in ("horario", "dia", "quando")):
            signals["horarios"].update(q_tokens)
        if "experimental" in qn or "agendo" in qn:
            signals["experimental"].update(q_tokens)
        if any(
            t in qn
            for t in ("endereco", "onde", "local", "levar", "chinelo", "retirar", "retirada")
        ):
            signals["faq"].update(q_tokens)
        if any(t in qn for t in ("quem", "sobre", "nome", "diferenca")):
            signals["faq"].update(q_tokens)

    contato = base.secoes.get("endereco e contato", "")
    if contato:
        signals["faq"].update({"endereco", "endereço", "onde fica", "local", "maps"})

    sobre = base.secoes.get("sobre", "")
    if sobre:
        signals["faq"].update({"sobre", "quem"})

    return {k: v for k, v in signals.items() if v}


def build_facts_from_base(base: KnowledgeBase) -> KnowledgeFacts:
    como_comprar = base.secoes.get("como comprar e pagamento", "")
    monthly, semester, known = _parse_prices(base)
    return KnowledgeFacts(
        business_name=base.titulo,
        item_names=[item.nome for item in base.itens.values()],
        experimental_slots=_parse_experimental_slots(como_comprar, base),
        regular_days_by_item=_parse_regular_days(base),
        monthly_price=monthly,
        semester_price=semester,
        known_plan_prices=known,
        intent_signals=_build_intent_signals(base),
        experimental_has_price=False,
    )


_facts: KnowledgeFacts | None = None


def get_knowledge_facts() -> KnowledgeFacts:
    global _facts
    if _facts is None:
        _facts = build_facts_from_base(get_knowledge_store().get())
    return _facts


def reset_knowledge_facts_cache() -> None:
    global _facts
    _facts = None
