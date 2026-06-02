"""Domain pure functions."""

from __future__ import annotations

import re
from typing import List

from .priority import calcular_prioridade_handover

_HANDOVER_TOKEN = re.compile(r"\[human_handover\]", re.I)


def detectar_pedido_atendimento_humano(user_message: str) -> bool:
    """Detect handover when the customer explicitly asks for a human."""
    if not user_message:
        return False
    normalized = user_message.lower()
    keywords: List[str] = [
        "atendimento humano",
        "falar com humano",
        "falar com um humano",
        "falar com atendente",
        "falar com um atendente",
        "falar com a secretaria",
        "falar com secretaria",
        "quero a secretaria",
        "quero falar com a secretaria",
        "preciso da secretaria",
        "preciso falar com a secretaria",
        "chamar a secretaria",
        "chamar secretaria",
        "quero um atendente",
        "preciso de um atendente",
        "pessoa real",
    ]
    return any(kw in normalized for kw in keywords)


def detectar_intencao_human_handoff(model_output: str) -> bool:
    """True only when the model explicitly signals handover via [HUMAN_HANDOVER]."""
    if not model_output:
        return False
    return bool(_HANDOVER_TOKEN.search(model_output))


def strip_handover_token(model_output: str) -> str:
    """Remove the handover token from a model reply before sending to the customer."""
    return _HANDOVER_TOKEN.sub("", model_output).strip()


def build_handover_customer_message(model_reply: str) -> str:
    """Customer-facing message when the model requests secretariat handover."""
    explanation = strip_handover_token(model_reply)
    if explanation:
        return (
            f"{explanation}\n\n"
            "_Em seguida, nossa secretaria dará continuidade ao seu atendimento._"
        )
    return (
        "Vou encaminhar você para a secretaria. "
        "Em breve um atendente humano continuará a conversa por aqui."
    )


def executar_handover_para_secretaria(
    phone: str,
    contact_id: int,
    whatsapp,
    db,
    logger,
    motivo: str = "pedido_do_cliente",
    push_name: str | None = None,
    user_message: str | None = None,
    simulated: bool = False,
    customer_message: str | None = None,
) -> dict:
    """Stop the bot, enqueue for secretariat, and notify admin if thresholds met."""
    from .queue import check_long_wait_notifications, process_new_handover

    prioridade = calcular_prioridade_handover(user_message or "")

    handover_text = customer_message or (
        "Encaminhando você para a secretaria. "
        "Em breve um atendente humano continuará a conversa por aqui."
    )
    if not simulated:
        whatsapp.send_text(
            phone,
            handover_text,
            source="handover",
            contact_id=contact_id,
            simulated=simulated,
        )
    db.save_message(contact_id, direction="out", text=handover_text)
    db.enroll_handover(
        contact_id, motivo=motivo, push_name=push_name, prioridade=prioridade
    )
    logger.info(
        "Handover para secretaria (%s, prio=%s): %s", motivo, prioridade, phone
    )

    if simulated:
        notify_result = {"skipped": "simulated"}
        long_wait_result = {}
    else:
        waiting = db.get_contact_waiting(phone)
        notify_result = process_new_handover(db, whatsapp, contact=waiting)
        long_wait_result = check_long_wait_notifications(db, whatsapp)

    return {
        "ok": True,
        "handed_to_human": True,
        "reason": motivo,
        "prioridade": prioridade,
        "admin_notify": notify_result,
        "long_wait_check": long_wait_result,
    }
