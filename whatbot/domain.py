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
    """Customer-facing message when the model requests human handover."""
    explanation = strip_handover_token(model_reply)
    if explanation:
        return (
            f"{explanation}\n\n"
            "_Em seguida, um atendente humano continua o seu atendimento._"
        )
    return (
        "Vou encaminhar você para um atendente. "
        "Em breve alguém da nossa equipe continua a conversa por aqui."
    )


def executar_handover_para_secretaria(
    phone: str,
    contact_id: int,
    router,
    db,
    logger,
    motivo: str = "pedido_do_cliente",
    push_name: str | None = None,
    user_message: str | None = None,
    simulated: bool = False,
    customer_message: str | None = None,
    canal: str | None = None,
    order: dict | None = None,
) -> dict:
    """Stop the bot, enqueue for secretariat, and notify admin if thresholds met.

    The customer is answered on their own channel; admins are always notified on
    the admin channel (WhatsApp).

    `order` (a catalog order dict from `whatbot/webhook.py::_extract_order`,
    or `None`) forces priority 1 unconditionally when present — see
    openspec/changes/catalog-order-capture/design.md, Decisão 3.
    """
    from .channels import send_to_contact
    from .queue import check_long_wait_notifications, process_new_handover

    prioridade = calcular_prioridade_handover(user_message or "", order=order)

    handover_text = customer_message or (
        "Encaminhando você para um atendente. "
        "Em breve alguém da nossa equipe continua a conversa por aqui."
    )
    if not simulated:
        send_to_contact(
            router,
            phone,
            handover_text,
            canal=canal,
            source="handover",
            contact_id=contact_id,
            simulated=simulated,
            human_agent=True,
        )

    # The handover confirmation is already delivered to the customer (or this
    # is a simulation, where nothing was sent) at this point — every step
    # below must stay best-effort and never let the caller see anything but
    # `ok: True`. `main()` deletes the webhook-idempotency record whenever the
    # result isn't `ok`, and the next redelivery of the same `message_id`
    # would reprocess from scratch and resend the handover message to the
    # real customer (same class of bug already fixed for the LLM reply path
    # in `main.py::process_customer_message`).
    notify_result: dict = {"skipped": "simulated"} if simulated else {}
    long_wait_result: dict = {}
    if not simulated:
        # Guarded by `not simulated`: a simulated handover must not leave a
        # trace in the real contact's message history, nor deactivate the
        # bot / enroll the real contact in the secretariat queue.
        try:
            db.save_message(contact_id, direction="out", text=handover_text)
            db.enroll_handover(
                contact_id, motivo=motivo, push_name=push_name, prioridade=prioridade
            )
        except Exception:
            logger.exception(
                "Erro registrando handover (bookkeeping pós-envio, best-effort): %s",
                phone,
            )
        try:
            waiting = db.get_contact_waiting(phone, canal=canal)
            notify_result = process_new_handover(
                db, router, contact=waiting, last_order=order
            )
            long_wait_result = check_long_wait_notifications(db, router)
        except Exception:
            logger.exception(
                "Erro notificando admin sobre handover (best-effort): %s", phone
            )
            notify_result = {"skipped": "notify_failed"}
            long_wait_result = {}

    logger.info(
        "Handover para secretaria (%s, prio=%s): %s", motivo, prioridade, phone
    )

    return {
        "ok": True,
        "handed_to_human": True,
        "reason": motivo,
        "prioridade": prioridade,
        "admin_notify": notify_result,
        "long_wait_check": long_wait_result,
        # The text a real customer would see for this turn — every branch of
        # `process_customer_message` that can produce a customer-facing reply
        # DEVE preencher esta chave (não só `model_reply`, que só existe no
        # caminho de resposta direta da LLM). É o que permite que
        # `run_admin_simulation` só decore o texto, sem adivinhar qual chave
        # do result carrega a resposta (openspec/project.md não documenta
        # isso ainda — nasceu de um bug real de simulação despejando o dict
        # cru quando o turno terminava em handover sem `model_reply`).
        "customer_reply_text": handover_text,
    }
