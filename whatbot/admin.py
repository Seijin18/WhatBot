"""Organic secretariat assistant — natural language + disambiguation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .admin_nlu import parse_admin_intent
from .config import AUTO_REACTIVATE_HOURS
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

HELP_TEXT = """*Secretaria — fale naturalmente*

Exemplos:
• *Quem está na fila?*
• *Assumo a Maria* / *Vou atender o João*
• *Finalizei com a Maria* / *Atendi o 5511...*
• *Libera o bot para o João* / *Bot pode voltar a falar com Maria*

Se houver *duas Marias*, o bot pergunta qual delas (responda *1*, *2* ou o telefone).

*Testar como cliente* (do seu celular admin):
• Envie *teste*, *olá* ou *oi* — o bot simula um cliente e responde aqui
• `#simular 5511999999999 Olá, quero judô`
• `#simular Olá` (usa número de teste padrão)

⚠️ O número *5511949305094* é a linha da associação (WhatsApp Business). Mensagens *de* esse app saem como *fromMe* e não simulam cliente. Teste pelo celular pessoal admin ou `#simular`.

*Automações:*
• Responder um cliente → sai da fila; bot reativa sozinho em *{hours}h*
• Alertas de fila continuam automáticos
""".format(
    hours=AUTO_REACTIVATE_HOURS
)


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
        return _reply(router, db, admin_phone, contact_id, HELP_TEXT)

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
