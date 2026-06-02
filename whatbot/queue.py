"""Attendance queue notifications for admin phones."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import List
from zoneinfo import ZoneInfo

from .config import (
    AUTO_REACTIVATE_HOURS,
    DAILY_SUMMARY_HOUR,
    NOTIFY_IMMEDIATE_ON_HANDOVER,
    NOTIFY_ON_ASSUMIR,
    get_admin_phones,
    get_timezone,
    NOTIFY_LONG_WAIT_MINUTES,
    NOTIFY_QUEUE_BATCH,
)
from .db import Database, WaitingContact
from .priority import prioridade_label

logger = logging.getLogger("whatbot.queue")


def normalize_phone(phone: str) -> str:
    raw = phone.split("@", 1)[0]
    return re.sub(r"\D", "", raw)


def is_admin_phone(phone: str) -> bool:
    admins = get_admin_phones()
    if not admins:
        return False
    return normalize_phone(phone) in admins


def format_admin_phone_label(phone: str | None) -> str:
    if not phone:
        return "—"
    if phone == "whatsapp_business":
        return "WhatsApp Business"
    return phone


def format_waiting_list(
    contacts: List[WaitingContact],
    title: str,
    include_last_message: bool = False,
    db: Database | None = None,
) -> str:
    if not contacts:
        return "Nenhum contato aguardando atendimento no momento."

    lines = [title, ""]
    for idx, contact in enumerate(contacts, start=1):
        name = contact.push_name or "Sem nome"
        motivo = contact.handover_motivo or "handover"
        prio = prioridade_label(contact.prioridade)
        assumido = format_admin_phone_label(contact.assumido_por)
        lines.append(
            f"{idx}. *{name}* — {contact.phone}\n"
            f"   {prio} | {contact.minutes_waiting} min | Motivo: {motivo}\n"
            f"   Assumido por: {assumido}"
        )
        if include_last_message and db is not None:
            last_msg = db.get_last_inbound_message(contact.id)
            if last_msg:
                preview = last_msg[:120] + ("..." if len(last_msg) > 120 else "")
                lines.append(f"   Última msg: {preview}")
    lines.append("")
    lines.append(f"Total na fila: {len(contacts)}")
    lines.append(
        "Fale naturalmente: *quem está na fila?* | *assumo a Maria* | *finalizei com o João*"
    )
    return "\n".join(lines)


def notify_admin(
    whatsapp,
    message: str,
    exclude_phones: List[str] | None = None,
) -> bool:
    admins = get_admin_phones()
    if not admins:
        logger.debug("ADMIN_NOTIFY_PHONES não configurado; notificação ignorada")
        return False
    excluded = {normalize_phone(p) for p in (exclude_phones or [])}
    sent = False
    for admin_phone in admins:
        if admin_phone in excluded:
            continue
        try:
            whatsapp.send_text(admin_phone, message, source="admin_notify")
            logger.info("Notificação enviada ao admin %s", admin_phone)
            sent = True
        except Exception:
            logger.exception("Falha ao notificar admin %s", admin_phone)
            return False
    return sent


def notify_all_admins_except(whatsapp, message: str, except_phone: str) -> bool:
    return notify_admin(whatsapp, message, exclude_phones=[except_phone])


def process_new_handover(
    db: Database,
    whatsapp,
    contact: WaitingContact | None = None,
) -> dict:
    """Notify admins immediately and on batch threshold."""
    result: dict = {"batch_count": db.increment_handover_batch(), "notified": False}

    if NOTIFY_IMMEDIATE_ON_HANDOVER and contact is not None:
        prio = prioridade_label(contact.prioridade)
        waiting = db.get_waiting_contacts()
        msg = (
            f"🆕 *Novo na fila* — {contact.push_name or 'Sem nome'} ({contact.phone})\n"
            f"Prioridade: {prio} | Total na fila: {len(waiting)}"
        )
        if notify_admin(whatsapp, msg):
            result["immediate"] = True

    if result["batch_count"] >= NOTIFY_QUEUE_BATCH:
        waiting = db.get_waiting_contacts()
        title = (
            f"🔔 *{len(waiting)} contato(s) aguardando* "
            f"(lote de {NOTIFY_QUEUE_BATCH} handovers)"
        )
        message = format_waiting_list(waiting, title, include_last_message=True, db=db)
        if notify_admin(whatsapp, message):
            db.reset_handover_batch()
            result["notified"] = True
            result["reason"] = "batch_threshold"

    return result


def handle_staff_outgoing_message(
    to_phone: str,
    db: Database,
    whatsapp,
) -> dict:
    """When secretariat replies via WhatsApp Business, auto-complete queue entry."""
    waiting = db.get_contact_waiting(to_phone)
    if waiting is None:
        return {"ok": True, "ignored": True, "reason": "not_in_queue"}

    if db.mark_attended(
        to_phone,
        reativar_bot=False,
        assumido_por="whatsapp_business",
        schedule_resume_hours=AUTO_REACTIVATE_HOURS,
    ):
        name = waiting.push_name or to_phone
        notify_admin(
            whatsapp,
            f"✅ *{name}* ({to_phone}) atendido via WhatsApp Business.\n"
            f"Bot reativa automaticamente em {AUTO_REACTIVATE_HOURS}h.",
        )
        logger.info("Auto-atendido após resposta WhatsApp Business: %s", to_phone)
        return {"ok": True, "auto_attended": True, "phone": to_phone}

    return {"ok": True, "ignored": True}


def notify_assumption(
    whatsapp,
    admin_phone: str,
    contact: WaitingContact,
) -> None:
    if not NOTIFY_ON_ASSUMIR:
        return
    name = contact.push_name or contact.phone
    msg = (
        f"📌 *Atendimento assumido*\n"
        f"{name} ({contact.phone}) — por {admin_phone}"
    )
    notify_all_admins_except(whatsapp, msg, admin_phone)


def check_long_wait_notifications(db: Database, whatsapp) -> dict:
    if not get_admin_phones():
        return {"checked": True, "notified": False}

    unnotified = db.get_long_wait_unnotified(NOTIFY_LONG_WAIT_MINUTES)
    if not unnotified:
        return {"checked": True, "notified": False}

    title = (
        f"⏰ *Espera prolongada* — {len(unnotified)} contato(s) "
        f"há mais de {NOTIFY_LONG_WAIT_MINUTES} min"
    )
    message = format_waiting_list(unnotified, title, include_last_message=True, db=db)
    if notify_admin(whatsapp, message):
        db.mark_long_wait_notified([c.id for c in unnotified])
        return {"checked": True, "notified": True, "count": len(unnotified)}
    return {"checked": True, "notified": False}


def build_daily_summary(db: Database, day: date | None = None) -> str:
    tz = ZoneInfo(get_timezone())
    target = day or datetime.now(tz).date()
    stats = db.get_daily_handover_stats(target)
    total_handovers = db.count_handovers_today(target)
    return (
        f"📊 *Resumo do dia* — {target.strftime('%d/%m/%Y')}\n\n"
        f"Handovers: {total_handovers}\n"
        f"Atendidos: {stats['atendidos']}\n"
        f"Tempo médio de espera: {stats['avg_wait_minutes']} min\n"
        f"Prioridade alta: {stats['alta_prioridade']}\n"
        f"Ainda na fila: {stats['still_waiting']}"
    )


def send_daily_summary_if_due(db: Database, whatsapp) -> dict:
    if not get_admin_phones():
        return {"sent": False, "reason": "no_admins"}

    tz = ZoneInfo(get_timezone())
    now = datetime.now(tz)
    if now.hour < DAILY_SUMMARY_HOUR:
        return {"sent": False, "reason": "before_summary_hour"}

    today = now.date()
    if db.was_daily_summary_sent(today):
        return {"sent": False, "reason": "already_sent"}

    message = build_daily_summary(db, today)
    if notify_admin(whatsapp, message):
        db.mark_daily_summary_sent(today)
        return {"sent": True, "date": str(today)}
    return {"sent": False, "reason": "notify_failed"}


def run_periodic_queue_checks(db: Database, whatsapp) -> dict:
    reactivated = db.process_auto_reactivations()
    if reactivated:
        notify_admin(
            whatsapp,
            f"🤖 Bot reativado automaticamente para {len(reactivated)} contato(s):\n"
            + ", ".join(reactivated),
        )
    long_wait = check_long_wait_notifications(db, whatsapp)
    daily = send_daily_summary_if_due(db, whatsapp)
    return {
        "reactivated": reactivated,
        "long_wait": long_wait,
        "daily_summary": daily,
    }
