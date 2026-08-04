"""Detect handover priority from customer messages."""

from __future__ import annotations

PRIORITY_KEYWORDS = [
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
    "preco",
    "preço",
    "valor",
    "quanto custa",
    # Non-enrollment "ready to buy" signals — a customer asking to place an
    # order is just as much a hot lead as one asking to enroll, but the
    # original list only covered class/enrollment vocabulary (see
    # docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.8).
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


def calcular_prioridade_handover(user_message: str) -> int:
    """Return 1 for hot leads (enrollment intent), 0 otherwise."""
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
