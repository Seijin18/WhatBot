"""Attendance queue notifications for admin phones."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any, List
from zoneinfo import ZoneInfo

from .config import (
    DAILY_SUMMARY_HOUR,
    NOTIFY_IMMEDIATE_ON_HANDOVER,
    NOTIFY_ON_ASSUMIR,
    get_admin_phones,
    get_timezone,
    NOTIFY_LONG_WAIT_MINUTES,
    NOTIFY_QUEUE_BATCH,
)
from .channels import channel_label, messaging_window, send_admin
from .db import Database, MessageRecord, WaitingContact, resolve_label
from .instagram_health import run_instagram_health_checks
from .priority import prioridade_label
from .session_state import SessionState, history_summary

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


# Portuguese labels for `contatos.status` (contact-interest-memory) — none of
# the existing helpers (`prioridade_label`, `channel_label`) cover the
# business stage, and `build_contact_summary` is the first place that needs
# to render it to a human.
_STATUS_LABELS: dict[str, str] = {
    "novo_lead": "novo lead",
    "interessado": "interessado",
    "comprando": "comprando",
    "cliente_ativo": "cliente ativo",
    "cancelado": "cancelado",
}


def _format_price(preco: Any) -> str:
    """pt-BR currency formatting (`49,90`, not the raw `49.9`) — user-facing
    text stays in Portuguese (`openspec/project.md`)."""
    return f"{float(preco):.2f}".replace(".", ",")


def _format_resolved_order_item(item: dict) -> str:
    nome = item.get("nome") or item.get("product_id") or "item"
    quantity = item.get("quantity")
    preco = item.get("preco")
    # `quantity` is the count already captured by `catalog-order-capture`
    # (`order["items"][i]["quantity"]`, merged in by `_resolve_order_for_summary`)
    # — a 3-unit order must not read the same as a 1-unit order (critic
    # finding: "já sabe o que entregar/cobrar" in the proposal's "Why").
    label = f"{nome} x{quantity}" if quantity and quantity != 1 else nome
    if preco is None:
        return label
    price = _format_price(preco)
    suffix = " cada" if quantity and quantity != 1 else ""
    return f"{label} (R$ {price}{suffix})"


def _format_order_summary(order: dict) -> str:
    """Portuguese line summarizing a catalog order for the admin notification.

    `order` is expected already enriched by the caller with a
    `resolved_items` key (via `Database.resolve_catalog_items`, see
    `_resolve_order_for_summary`) when `items_identifiable` and the catalog
    cache had a match — keeps `build_contact_summary` itself free of a
    `Database` dependency (design.md, Decisão 2).
    """
    if not order.get("items_identifiable"):
        return (
            "Pedido do catálogo — itens não identificados, confirmar com o "
            "cliente."
        )
    resolved = order.get("resolved_items") or []
    if not resolved:
        # catalog-product-sync unavailable, or the cache had no match for any
        # of these productIds — degrade entirely to the raw data
        # `catalog-order-capture` already captured (design.md, Decisão 2).
        title = order.get("order_title") or "Pedido do catálogo"
        count = order.get("item_count")
        return f"Pedido: {title} ({count} item(ns))" if count else f"Pedido: {title}"

    items_str = "; ".join(_format_resolved_order_item(r) for r in resolved)
    # Partial cache hit for THIS order (design.md, Decisão 2: "cache vazio
    # para um productId específico" — the degradation is per-item, not
    # all-or-nothing): list what IS known and flag what's missing, rather
    # than silently showing a shorter order than the customer actually sent.
    requested_ids = {
        item.get("productId")
        for item in order.get("items") or []
        if item.get("productId")
    }
    resolved_ids = {item.get("product_id") for item in resolved}
    missing = len(requested_ids - resolved_ids)
    if missing:
        items_str += f"; + {missing} item(ns) não identificado(s)"
    return f"Pedido: {items_str}"


def build_contact_summary(
    contact: WaitingContact,
    session_state: SessionState | dict | None,
    last_order: dict | None = None,
    history: List[MessageRecord] | None = None,
) -> str:
    """Short, deterministic Portuguese summary of a contact's business stage,
    interest and (when this handover was triggered by one) catalog order —
    for the admin handover notification (handover-summary-for-agent).

    No LLM call (design.md, Decisão 1) — reuses `history_summary()` for the
    recent-topics line and adds the business-stage/interest/order signals
    already available on `contact`/`session_state`. Returns `""` when there
    is nothing to show (Requirement "Contato sem nenhum sinal de interesse",
    Scenario "Contato sem nenhum sinal de interesse") — callers must skip the
    section entirely in that case rather than render an empty header.
    """
    session = (
        session_state
        if isinstance(session_state, SessionState)
        else SessionState.from_dict(session_state)
    )

    lines: List[str] = []

    status = getattr(contact, "status", None)
    if status:
        lines.append(f"Estágio: {_STATUS_LABELS.get(status, status)}")

    if session.item_interesse:
        lines.append(f"Interesse: {', '.join(session.item_interesse)}")

    if history:
        topics = history_summary(history)
        if topics:
            lines.append(topics)

    if last_order is not None:
        lines.append(_format_order_summary(last_order))

    return "\n".join(lines)


def _resolve_order_for_summary(db: Database, order: dict | None) -> dict | None:
    """Enrich a catalog order dict with `resolved_items` (name/price via
    `Database.resolve_catalog_items`, `quantity` merged back in from the
    order's own `items`) before handing it to `build_contact_summary` — keeps
    that function free of a `Database` dependency (design.md, Decisão 2).
    Best-effort: a resolution failure falls back to the order's raw data,
    never blocks the notification."""
    if order is None:
        return None
    resolved_items: List[dict] = []
    if order.get("items_identifiable"):
        # `Database.resolve_catalog_items` only returns product_id/nome/
        # preco/disponivel — `quantity` lives on the order's own `items`
        # (captured by `catalog-order-capture`) and must be merged back in
        # here, or every resolved item reads as a single unit regardless of
        # how many the customer actually ordered.
        quantities: dict[str, Any] = {
            item.get("productId"): item.get("quantity")
            for item in order.get("items") or []
            if item.get("productId")
        }
        try:
            resolved = db.resolve_catalog_items(list(quantities))
        except Exception:
            logger.exception(
                "Falha ao resolver itens do catálogo para o resumo do handover"
            )
            resolved = []
        resolved_items = [
            {**item, "quantity": quantities.get(item.get("product_id"))}
            for item in resolved
        ]
    return {**order, "resolved_items": resolved_items}


def _recent_messages_for_summary(
    db: Database, contact_id: int, limit: int = 6
) -> List[MessageRecord]:
    """Best-effort recent-message fetch feeding `build_contact_summary`'s
    `history_summary()` base — a failure must not break the notification."""
    try:
        return db.get_recent_messages(contact_id, limit=limit)
    except Exception:
        logger.exception("Falha ao carregar histórico para o resumo do handover")
        return []


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
        # Identity chip alongside `name` — same precedence contract as
        # `WaitingContact.label` (whatbot/db.py:resolve_label), minus the
        # name itself since it is already shown separately here.
        identity = resolve_label(None, contact.handle, contact.external_id or contact.phone) or "?"
        canal = channel_label(contact.canal)
        lines.append(
            f"{idx}. *{name}* — {identity} · {canal}\n"
            f"   {prio} | {contact.minutes_waiting} min | Motivo: {motivo}\n"
            f"   Assumido por: {assumido}"
        )
        # Prazo de resposta (janela de mensageria do Instagram, ver
        # `openspec/changes/instagram-messaging-window`) — mais importante
        # justamente aqui: um contato esperando há tempo é quem tem mais
        # chance de estar perto do fim da janela.
        deadline_note = window_deadline_note(contact)
        if deadline_note:
            lines.append(f"   Prazo de resposta: {deadline_note}")
        if include_last_message and db is not None:
            # handover-summary-for-agent (Decisão 3, design.md): reuses
            # `build_contact_summary` instead of the raw 120-char preview this
            # used to show, so the immediate handover notification and this
            # on-demand listing never diverge on what they surface.
            history = _recent_messages_for_summary(db, contact.id)
            summary = build_contact_summary(
                contact, contact.session_state, history=history
            )
            if summary:
                for line in summary.split("\n"):
                    lines.append(f"   {line}")
    lines.append("")
    lines.append(f"Total na fila: {len(contacts)}")
    lines.append(
        "Fale naturalmente: *quem está na fila?* | *assumo a Maria* | *finalizei com o João*"
    )
    return "\n".join(lines)


def window_deadline_note(contact: WaitingContact, now: datetime | None = None) -> str | None:
    """Portuguese note on the contact's messaging-window response deadline.

    `None` when the contact's channel imposes no messaging window (e.g.
    WhatsApp) or `last_inbound_at` is unknown — nothing to add to the
    notification in that case (see `openspec/changes/instagram-messaging-window`,
    Requirement "Notificação de fila informa prazo de resposta").
    """
    window = messaging_window(contact.canal)
    if not window or contact.last_inbound_at is None:
        return None

    standard, human_agent = window
    now = now or datetime.now(timezone.utc)
    elapsed = now - contact.last_inbound_at
    tz = ZoneInfo(get_timezone())

    def _fmt(dt: datetime) -> str:
        return dt.astimezone(tz).strftime("%d/%m %H:%M")

    if elapsed <= standard:
        deadline = contact.last_inbound_at + standard
        return f"responder em até 24h (janela livre até {_fmt(deadline)})"
    if elapsed <= human_agent:
        deadline = contact.last_inbound_at + human_agent
        return (
            "janela de 24h encerrada — só via atendimento humano, até "
            f"{_fmt(deadline)} (7 dias)"
        )
    return "janela de mensageria encerrada (fora de 7 dias)"


def notify_admin(
    router,
    message: str,
    exclude_phones: List[str] | None = None,
) -> bool:
    """Notify admins. Always delivered on the admin channel (WhatsApp)."""
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
            send_admin(router, admin_phone, message, source="admin_notify")
            logger.info("Notificação enviada ao admin %s", admin_phone)
            sent = True
        except Exception:
            logger.exception("Falha ao notificar admin %s", admin_phone)
            return False
    return sent


def notify_all_admins_except(router, message: str, except_phone: str) -> bool:
    return notify_admin(router, message, exclude_phones=[except_phone])


def process_new_handover(
    db: Database,
    router,
    contact: WaitingContact | None = None,
    last_order: dict | None = None,
) -> dict:
    """Notify admins immediately and on batch threshold.

    `last_order` (a catalog order dict from
    `whatbot/webhook.py::_extract_order`, threaded from
    `executar_handover_para_secretaria`, or `None`) feeds the order section
    of `build_contact_summary` when this handover was triggered by a catalog
    order — see `openspec/changes/handover-summary-for-agent`.
    """
    result: dict = {"batch_count": db.increment_handover_batch(), "notified": False}

    if NOTIFY_IMMEDIATE_ON_HANDOVER and contact is not None:
        prio = prioridade_label(contact.prioridade)
        waiting = db.get_waiting_contacts()
        identity = resolve_label(None, contact.handle, contact.external_id or contact.phone) or "?"
        canal = channel_label(contact.canal)
        msg = (
            f"🆕 *Novo na fila* — {contact.push_name or 'Sem nome'} ({identity} · {canal})\n"
            f"Prioridade: {prio} | Total na fila: {len(waiting)}"
        )
        deadline_note = window_deadline_note(contact)
        if deadline_note:
            msg += f"\nPrazo de resposta: {deadline_note}"
        history = _recent_messages_for_summary(db, contact.id)
        order_for_summary = _resolve_order_for_summary(db, last_order)
        summary = build_contact_summary(
            contact, contact.session_state, last_order=order_for_summary, history=history
        )
        if summary:
            msg += f"\n\n{summary}"
        if notify_admin(router, msg):
            result["immediate"] = True

    if result["batch_count"] >= NOTIFY_QUEUE_BATCH:
        waiting = db.get_waiting_contacts()
        title = (
            f"🔔 *{len(waiting)} contato(s) aguardando* "
            f"(lote de {NOTIFY_QUEUE_BATCH} handovers)"
        )
        message = format_waiting_list(waiting, title, include_last_message=True, db=db)
        if notify_admin(router, message):
            db.reset_handover_batch()
            result["notified"] = True
            result["reason"] = "batch_threshold"

    return result


def handle_staff_outgoing_message(
    to_phone: str,
    db: Database,
    router,
) -> dict:
    """When secretariat replies via WhatsApp Business, auto-complete queue entry."""
    waiting = db.get_contact_waiting(to_phone)
    if waiting is None:
        return {"ok": True, "ignored": True, "reason": "not_in_queue"}

    if db.mark_attended(
        to_phone,
        reativar_bot=True,
        assumido_por="whatsapp_business",
    ):
        name = waiting.push_name or to_phone
        notify_admin(
            router,
            f"✅ *{name}* ({to_phone}) atendido via WhatsApp Business.\n"
            "Bot já está ativo de novo.",
        )
        logger.info("Auto-atendido após resposta WhatsApp Business: %s", to_phone)
        return {"ok": True, "auto_attended": True, "phone": to_phone}

    return {"ok": True, "ignored": True}


def notify_assumption(
    router,
    admin_phone: str,
    contact: WaitingContact,
) -> None:
    if not NOTIFY_ON_ASSUMIR:
        return
    name = contact.label
    identity = resolve_label(None, contact.handle, contact.external_id or contact.phone) or "?"
    canal = channel_label(contact.canal)
    msg = (
        f"📌 *Atendimento assumido*\n"
        f"{name} ({identity} · {canal}) — por {admin_phone}"
    )
    notify_all_admins_except(router, msg, admin_phone)


def check_long_wait_notifications(db: Database, router) -> dict:
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
    if notify_admin(router, message):
        db.mark_long_wait_notified([c.id for c in unnotified])
        return {"checked": True, "notified": True, "count": len(unnotified)}
    return {"checked": True, "notified": False}


def build_daily_summary(db: Database, day: date | None = None) -> str:
    tz = ZoneInfo(get_timezone())
    target = day or datetime.now(tz).date()
    stats = db.get_daily_handover_stats(target)
    total_handovers = db.count_handovers_today(target)
    # Channel breakdown of who is still waiting, reusing the existing
    # `get_waiting_contacts()` method (not a schema/contract change) — costs
    # one extra query per call, acceptable since this runs ~1x/day plus
    # on-demand via the `resumo` command.
    still_waiting = db.get_waiting_contacts()
    por_canal: dict[str, int] = {}
    for contact in still_waiting:
        canal = channel_label(contact.canal)
        por_canal[canal] = por_canal.get(canal, 0) + 1
    canais_str = ", ".join(f"{canal}: {count}" for canal, count in sorted(por_canal.items()))
    ainda_na_fila = f"{stats['still_waiting']}"
    if canais_str:
        ainda_na_fila += f" ({canais_str})"
    return (
        f"📊 *Resumo do dia* — {target.strftime('%d/%m/%Y')}\n\n"
        f"Handovers: {total_handovers}\n"
        f"Atendidos: {stats['atendidos']}\n"
        f"Tempo médio de espera: {stats['avg_wait_minutes']} min\n"
        f"Prioridade alta: {stats['alta_prioridade']}\n"
        f"Ainda na fila: {ainda_na_fila}"
    )


def send_daily_summary_if_due(db: Database, router) -> dict:
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
    if notify_admin(router, message):
        db.mark_daily_summary_sent(today)
        return {"sent": True, "date": str(today)}
    return {"sent": False, "reason": "notify_failed"}


def run_periodic_queue_checks(db: Database, router) -> dict:
    reactivated = db.process_auto_reactivations()
    if reactivated:
        notify_admin(
            router,
            f"🤖 Bot reativado automaticamente para {len(reactivated)} contato(s):\n"
            + ", ".join(reactivated),
        )
    long_wait = check_long_wait_notifications(db, router)
    daily = send_daily_summary_if_due(db, router)

    # instagram-ingestion-service: limpeza periódica de `webhook_eventos`
    # (tasks.md 2.2) e alertas de saúde da integração (credencial perto de
    # expirar, silêncio prolongado de webhook) — reaproveita este job já
    # agendado em vez de criar outro só para isso (tasks.md 3.4).
    try:
        purged = db.purge_old_webhook_events()
    except Exception:
        logger.exception("Falha ao limpar webhook_eventos antigos")
        purged = 0
    try:
        instagram_health = run_instagram_health_checks(db, router)
    except Exception:
        logger.exception("Falha ao rodar checagens de saúde do Instagram")
        instagram_health = {}

    return {
        "reactivated": reactivated,
        "long_wait": long_wait,
        "daily_summary": daily,
        "webhook_events_purged": purged,
        "instagram_health": instagram_health,
    }
