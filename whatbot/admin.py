"""Organic secretariat assistant — natural language + disambiguation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .admin_nlu import parse_admin_intent
from .config import AUTO_REACTIVATE_HOURS, get_business_phone, resolve_simulate_phone
from .contact_resolver import (
    extract_phone_from_text,
    find_waiting_matches,
    format_disambiguation,
    pick_from_disambiguation,
    waiting_to_dict,
)
from .db import Database, WaitingContact
from .channels import WHATSAPP, channel_label, send_admin
from .queue import (
    build_daily_summary,
    format_waiting_list,
    normalize_phone,
    notify_assumption,
)

logger = logging.getLogger("whatbot.admin")


@dataclass
class TargetIdentity:
    """A contact identity resolved outside the waiting queue (e.g. reactivate).

    Mirrors the subset of `WaitingContact` that `_execute_action` needs
    (`external_id`, `canal`, `label`), so both types can be passed there
    interchangeably.
    """

    external_id: str
    canal: str
    label: str


# Persistent admin simulation mode (`#simular` alone / `#end-simular` alone
# — whatbot/admin_nlu.py). Reuses the `admin_sessao` table (same one the
# disambiguation flow below uses) instead of a new schema: it's already a
# per-admin_phone slot with a sliding 10-minute TTL (each save refreshes
# `created_at`, so an active simulation never expires while the admin keeps
# testing, and auto-clears itself if they forget to `#end-simular`). The
# `candidatos` JSONB column holds a single-element list with the simulated
# phone, the accumulated (capped) turn history, and the session state — so
# `whatbot.main._continue_admin_simulation` can carry conversational memory
# across turns without ever touching the real contact's message history
# (same isolation `simulated=True` already guarantees elsewhere).
_SIMULATE_ACAO = "simulacao_ativa"
SIMULATE_HISTORY_LIMIT = 6


def start_admin_simulation(db: Database, admin_phone: str, canal: str) -> str:
    """Turn on persistent simulation mode; returns the simulated phone in use."""
    sim_phone = resolve_simulate_phone(None)
    db.save_admin_sessao(
        admin_phone,
        _SIMULATE_ACAO,
        [{"sim_phone": sim_phone, "canal": canal, "history": [], "session_state": {}}],
    )
    return sim_phone


def get_active_admin_simulation(db: Database, admin_phone: str) -> dict | None:
    """Active simulation state for `admin_phone`, or `None` if there isn't
    one (never started, already ended, or expired)."""
    sessao = db.get_admin_sessao(admin_phone)
    if not sessao:
        return None
    acao, candidatos = sessao
    if acao != _SIMULATE_ACAO or not candidatos:
        return None
    return candidatos[0]


def save_active_admin_simulation(db: Database, admin_phone: str, state: dict) -> None:
    """Persist updated simulation state (new turn appended, refreshed
    session_state) — also refreshes the sliding TTL."""
    db.save_admin_sessao(admin_phone, _SIMULATE_ACAO, [state])


def end_admin_simulation(db: Database, admin_phone: str) -> None:
    db.clear_admin_sessao(admin_phone)


def _build_help_text() -> str:
    # The business's own WhatsApp Business line is read from
    # `BUSINESS_PHONE` (`config.get_business_phone()`) rather than
    # hardcoded: a literal number here would silently point at a *different*
    # business's line once this bot is redeployed for a new KB
    # (docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.8).
    business_phone = get_business_phone()
    warning = (
        f"\n⚠️ O número *{business_phone}* é a linha do WhatsApp Business. "
        "Mensagens *de* esse app saem como *fromMe* e não simulam cliente. "
        "Teste pelo celular pessoal admin ou `#simular`.\n"
        if business_phone
        else ""
    )
    return f"""*Atendimento — fale naturalmente*

Exemplos:
• *Quem está na fila?*
• *Assumo a Maria* / *Vou atender o João*
• *Finalizei com a Maria* / *Atendi o 5511...*
• *Libera o bot para o João* / *Bot pode voltar a falar com Maria*
• *Marca a Maria como cliente ativo* / *Confirma venda da Maria*

Se houver *duas Marias*, o bot pergunta qual delas (responda *1*, *2* ou o telefone).

*Testar como cliente* (do seu celular admin):
• Envie *teste*, *olá* ou *oi* — o bot simula um cliente e responde aqui
• `#simular 5511999999999 Olá, quero saber os preços`
• `#simular Olá` (usa número de teste padrão)
{warning}
*Automações:*
• Responder um cliente → sai da fila; bot reativa sozinho em *{AUTO_REACTIVATE_HOURS}h*
• Alertas de fila continuam automáticos
"""


def _reply(router, db, admin_phone: str, contact_id: int, text: str) -> dict:
    send_admin(router, admin_phone, text, source="admin")
    db.save_message(contact_id, direction="out", text=text)
    return {"ok": True, "admin_command": True, "reply": text}


def _try_pending_disambiguation(
    text: str, admin_phone: str, db: Database, router, contact_id: int
) -> dict | None:
    pending = db.get_admin_sessao(admin_phone)
    if not pending:
        return None

    acao, candidatos = pending
    picked = pick_from_disambiguation(text, candidatos)
    if not picked:
        return None

    db.clear_admin_sessao(admin_phone)
    return _execute_action(
        acao, picked, admin_phone, db, router, contact_id, picked.push_name
    )


def _execute_action(
    acao: str,
    target: WaitingContact | TargetIdentity,
    admin_phone: str,
    db: Database,
    router,
    contact_id: int,
    name: str | None = None,
) -> dict:
    label = name or target.label

    if acao == "assume":
        contact = db.assumir_contato(target.external_id, admin_phone, canal=target.canal)
        if contact:
            notify_assumption(router, admin_phone, contact)
            return _reply(
                router,
                db,
                admin_phone,
                contact_id,
                f"📌 Você assumiu *{label}*.",
            )
        return _reply(
            router, db, admin_phone, contact_id, f"{label} não está na fila."
        )

    if acao == "complete":
        if db.mark_attended(
            target.external_id,
            reativar_bot=False,
            assumido_por=admin_phone,
            schedule_resume_hours=AUTO_REACTIVATE_HOURS,
            canal=target.canal,
        ):
            return _reply(
                router,
                db,
                admin_phone,
                contact_id,
                f"✅ *{label}* atendido. Bot reativa automaticamente em {AUTO_REACTIVATE_HOURS}h.",
            )
        return _reply(
            router, db, admin_phone, contact_id, f"{label} não está na fila."
        )

    if acao == "reactivate":
        if db.reativar_bot(target.external_id, canal=target.canal):
            return _reply(
                router,
                db,
                admin_phone,
                contact_id,
                f"✅ Bot reativado para *{label}*.",
            )
        return _reply(
            router,
            db,
            admin_phone,
            contact_id,
            f"Contato {label} não encontrado.",
        )

    if acao == "pause":
        if db.pausar_bot(target.external_id, canal=target.canal):
            return _reply(
                router,
                db,
                admin_phone,
                contact_id,
                # "reativar {label}", não "libera o bot para {label}":
                # `_REACTIVATE` não engole o "para o/a" que sobraria antes
                # do nome, e `search_contacts_for_admin` faz substring cru
                # (não tokenizado) — a query final "para o {label}" nunca
                # bateria contra o `push_name` quando o alvo foi resolvido
                # por nome (o caso comum). "reativar {label}" funciona nos
                # dois casos (nome ou telefone) — ver
                # `TestPauseCommand.test_confirmation_message_suggests_a_command_that_actually_reactivates`.
                f"🔕 Bot pausado para *{label}*. Envie *reativar {label}* "
                "para retomar.",
            )
        return _reply(
            router,
            db,
            admin_phone,
            contact_id,
            f"Contato {label} não encontrado.",
        )

    if acao == "mark_active_client":
        # `set_contact_status` takes a numeric contact id, not the
        # `(external_id, canal)` identity `target` carries — mirrors how
        # every other branch above resolves through `db` by identity rather
        # than assuming `target` already has the row loaded (`WaitingContact`
        # from disambiguation vs. `TargetIdentity` from a direct match both
        # only guarantee `external_id`/`canal`/`label`).
        contact = db.get_contact_by_phone(target.external_id, canal=target.canal)
        if not contact:
            return _reply(
                router,
                db,
                admin_phone,
                contact_id,
                f"Contato {label} não encontrado.",
            )
        db.set_contact_status(contact.id, "cliente_ativo")
        return _reply(
            router,
            db,
            admin_phone,
            contact_id,
            f"✅ *{label}* marcado(a) como *cliente ativo*.",
        )

    return _reply(router, db, admin_phone, contact_id, "Ação desconhecida.")


def _resolve_waiting(
    query: str, acao: str, admin_phone: str, db: Database
) -> tuple[WaitingContact | None, str | None]:
    phone = extract_phone_from_text(query)
    if phone:
        waiting = db.get_contact_waiting(phone)
        if waiting:
            return waiting, None
        return None, f"*{phone}* não está na fila."

    matches = find_waiting_matches(query, db.get_waiting_contacts())
    if len(matches) == 1:
        return matches[0].contact, None
    if len(matches) > 1:
        top = matches[:5]
        db.save_admin_sessao(
            admin_phone, acao, [waiting_to_dict(m.contact) for m in top]
        )
        return None, format_disambiguation(top, acao)

    return None, f"Não encontrei *{query.strip()}* na fila. Envie *fila* para ver a lista."


def _resolve_reactivate(
    query: str, admin_phone: str, db: Database
) -> tuple[TargetIdentity | None, str | None]:
    phone = extract_phone_from_text(query)
    if phone:
        return TargetIdentity(external_id=phone, canal=WHATSAPP, label=phone), None

    rows = [r for r in db.search_contacts_for_admin(query) if not r["ia_ativa"]]
    if len(rows) == 1:
        r = rows[0]
        return (
            TargetIdentity(
                external_id=r["external_id"] or r["phone"],
                canal=r["canal"],
                label=r["label"],
            ),
            None,
        )
    if len(rows) > 1:
        candidatos = [
            {
                "id": r["id"],
                "phone": r["phone"],
                "push_name": r["push_name"],
                "minutes_waiting": 0,
                "prioridade": 0,
                "canal": r["canal"],
                "external_id": r["external_id"],
                "handle": r["handle"],
            }
            for r in rows[:5]
        ]
        db.save_admin_sessao(admin_phone, "reactivate", candidatos)
        lines = ["Encontrei vários contatos. Qual deles?"]
        for idx, r in enumerate(rows[:5], start=1):
            name = r["push_name"] or "Sem nome"
            fila = " (na fila)" if r["in_queue"] else ""
            canal = channel_label(r["canal"])
            lines.append(f"*{idx}.* {name} — {r['label']} · {canal}{fila}")
        lines.append("\nResponda com *1*, *2*... ou o telefone.")
        return None, "\n".join(lines)

    return None, f"Não encontrei contato inativo com bot desligado para *{query.strip()}*."


def _resolve_pause(
    query: str, admin_phone: str, db: Database
) -> tuple[TargetIdentity | None, str | None]:
    """Same resolution/disambiguation shape as `_resolve_reactivate`, but
    with the `ia_ativa` filter inverted (`admin-bot-pause`): only a contact
    that still has the bot active is offered as a target — a name match
    that turns out to already be paused gets an idempotent "já está
    pausado" reply instead of silently disappearing as "não encontrado"."""
    phone = extract_phone_from_text(query)
    if phone:
        return TargetIdentity(external_id=phone, canal=WHATSAPP, label=phone), None

    all_rows = db.search_contacts_for_admin(query)
    rows = [r for r in all_rows if r["ia_ativa"]]
    if len(rows) == 1:
        r = rows[0]
        return (
            TargetIdentity(
                external_id=r["external_id"] or r["phone"],
                canal=r["canal"],
                label=r["label"],
            ),
            None,
        )
    if len(rows) > 1:
        candidatos = [
            {
                "id": r["id"],
                "phone": r["phone"],
                "push_name": r["push_name"],
                "minutes_waiting": 0,
                "prioridade": 0,
                "canal": r["canal"],
                "external_id": r["external_id"],
                "handle": r["handle"],
            }
            for r in rows[:5]
        ]
        db.save_admin_sessao(admin_phone, "pause", candidatos)
        lines = ["Encontrei vários contatos. Qual deles?"]
        for idx, r in enumerate(rows[:5], start=1):
            name = r["push_name"] or "Sem nome"
            fila = " (na fila)" if r["in_queue"] else ""
            canal = channel_label(r["canal"])
            lines.append(f"*{idx}.* {name} — {r['label']} · {canal}{fila}")
        lines.append("\nResponda com *1*, *2*... ou o telefone.")
        return None, "\n".join(lines)

    if all_rows:
        return None, f"*{query.strip()}* já está com o bot pausado."
    return None, f"Não encontrei contato para *{query.strip()}*."


def _resolve_mark_active_client(
    query: str, admin_phone: str, db: Database
) -> tuple[TargetIdentity | None, str | None]:
    """Same resolution/disambiguation shape as `_resolve_reactivate`, minus
    the `ia_ativa` filter — marking a contact as `cliente_ativo`
    (contact-interest-memory) makes sense for any contact, active bot or
    not, unlike reactivating a silenced one."""
    phone = extract_phone_from_text(query)
    if phone:
        return TargetIdentity(external_id=phone, canal=WHATSAPP, label=phone), None

    rows = db.search_contacts_for_admin(query)
    if len(rows) == 1:
        r = rows[0]
        return (
            TargetIdentity(
                external_id=r["external_id"] or r["phone"],
                canal=r["canal"],
                label=r["label"],
            ),
            None,
        )
    if len(rows) > 1:
        candidatos = [
            {
                "id": r["id"],
                "phone": r["phone"],
                "push_name": r["push_name"],
                "minutes_waiting": 0,
                "prioridade": 0,
                "canal": r["canal"],
                "external_id": r["external_id"],
                "handle": r["handle"],
            }
            for r in rows[:5]
        ]
        db.save_admin_sessao(admin_phone, "mark_active_client", candidatos)
        lines = ["Encontrei vários contatos. Qual deles?"]
        for idx, r in enumerate(rows[:5], start=1):
            name = r["push_name"] or "Sem nome"
            fila = " (na fila)" if r["in_queue"] else ""
            canal = channel_label(r["canal"])
            lines.append(f"*{idx}.* {name} — {r['label']} · {canal}{fila}")
        lines.append("\nResponda com *1*, *2*... ou o telefone.")
        return None, "\n".join(lines)

    return None, f"Não encontrei contato para *{query.strip()}*."


def handle_admin_message(
    phone: str,
    text: str,
    db: Database,
    router,
    contact_id: int,
) -> dict:
    admin_phone = normalize_phone(phone)
    db.save_message(contact_id, direction="in", text=text)

    pending = _try_pending_disambiguation(text, admin_phone, db, router, contact_id)
    if pending:
        logger.info("Admin disambiguation resolved: %s", admin_phone)
        return pending

    intent = parse_admin_intent(text)

    if intent.action == "help":
        return _reply(router, db, admin_phone, contact_id, _build_help_text())

    if intent.action == "list_queue":
        waiting = db.get_waiting_contacts()
        body = format_waiting_list(
            waiting,
            f"📋 *Fila* ({len(waiting)} aguardando)",
            include_last_message=True,
            db=db,
        )
        return _reply(router, db, admin_phone, contact_id, body)

    if intent.action == "summary":
        return _reply(
            router, db, admin_phone, contact_id, build_daily_summary(db)
        )

    if intent.action == "complete_all":
        count = db.mark_all_attended(
            reativar_bot=False,
            assumido_por=admin_phone,
            schedule_resume_hours=AUTO_REACTIVATE_HOURS,
        )
        return _reply(
            router,
            db,
            admin_phone,
            contact_id,
            f"✅ {count} contato(s) atendidos. Bots reativam em {AUTO_REACTIVATE_HOURS}h.",
        )

    if intent.action == "assume" and intent.query:
        target, err = _resolve_waiting(intent.query, "assume", admin_phone, db)
        if err:
            return _reply(router, db, admin_phone, contact_id, err)
        return _execute_action(
            "assume", target, admin_phone, db, router, contact_id
        )

    if intent.action == "complete" and intent.query:
        target, err = _resolve_waiting(intent.query, "complete", admin_phone, db)
        if err:
            return _reply(router, db, admin_phone, contact_id, err)
        return _execute_action(
            "complete", target, admin_phone, db, router, contact_id
        )

    if intent.action == "reactivate" and intent.query:
        target, err = _resolve_reactivate(intent.query, admin_phone, db)
        if err:
            return _reply(router, db, admin_phone, contact_id, err)
        return _execute_action(
            "reactivate", target, admin_phone, db, router, contact_id
        )

    if intent.action == "pause" and intent.query:
        target, err = _resolve_pause(intent.query, admin_phone, db)
        if err:
            return _reply(router, db, admin_phone, contact_id, err)
        return _execute_action(
            "pause", target, admin_phone, db, router, contact_id
        )

    if intent.action == "mark_active_client" and intent.query:
        target, err = _resolve_mark_active_client(intent.query, admin_phone, db)
        if err:
            return _reply(router, db, admin_phone, contact_id, err)
        return _execute_action(
            "mark_active_client", target, admin_phone, db, router, contact_id
        )

    return _reply(
        router,
        db,
        admin_phone,
        contact_id,
        "Não entendi. Exemplos: *quem está na fila?*, *assumo a Maria*, "
        "*finalizei com o João*, *libera o bot para Maria*.\n\n"
        "Para testar: `#simular 5511... mensagem`\n"
        "Envie *ajuda* para ver tudo.",
    )
