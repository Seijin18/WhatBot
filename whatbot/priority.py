"""Detect handover priority from customer messages."""

from __future__ import annotations

# Two business shapes this bot supports (see
# docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.8): class/service enrollment
# ("matrícula") and direct product orders ("pedido"/"compra"). A hot lead in
# either shape scores the same; neither list assumes the other is absent.
_ENROLLMENT_KEYWORDS = [
    "matricula",
    "matricular",
    "matrícula",
    "inscrever",
    "inscrição",
    "inscricao",
    "aula experimental",
    "quero me inscrever",
    "fazer matricula",
    "fazer matrícula",
    "vaga",
    "vagas",
]

_ORDER_KEYWORDS = [
    "encomendar",
    "encomenda",
    "comprar",
    "fazer pedido",
    "quero comprar",
    "quero encomendar",
    "quero pedir",
    "fechar pedido",
    "fechar compra",
]

_PRICE_KEYWORDS = [
    "preco",
    "preço",
    "valor",
    "quanto custa",
]

PRIORITY_KEYWORDS = _ENROLLMENT_KEYWORDS + _ORDER_KEYWORDS + _PRICE_KEYWORDS


def calcular_prioridade_handover(user_message: str, order: dict | None = None) -> int:
    """Return 1 for hot leads (enrollment intent) or a catalog order, 0 otherwise.

    A catalog order (`order` not `None`) always scores 1, regardless of
    whether its items are identifiable — the handover is unconditional (see
    openspec/changes/catalog-order-capture/design.md, Decisão 3).
    """
    if order is not None:
        return 1
    if not user_message:
        return 0
    normalized = user_message.lower()
    import unicodedata

    folded = unicodedata.normalize("NFKD", normalized)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    if any(kw in ascii_text or kw in normalized for kw in PRIORITY_KEYWORDS):
        return 1
    return 0


def prioridade_label(prioridade: int) -> str:
    return "🔥 ALTA" if prioridade >= 1 else "normal"
