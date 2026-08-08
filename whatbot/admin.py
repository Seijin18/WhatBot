"""Organic secretariat assistant — natural language + disambiguation."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .admin_nlu import parse_admin_intent
from .config import get_business_phone, resolve_simulate_phone
from .contact_resolver import (
    extract_phone_from_text,
    extract_phone_list_from_text,
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


def _toggle_bot_for_phones(
    phones: list[str], activate: bool, db: Database
) -> tuple[list[str], list[str], list[str]]:
    """Applies pause/reactivate to each phone, skipping the mutation when
    the contact is already in the requested state (idempotent fallback,
    `admin-bulk-phone-toggle`).

    Returns `(mudou_agora, ja_estava, nao_encontrado)`, each a list of
    phones, in `phones` order.
    """
    mudou_agora: list[str] = []
    ja_estava: list[str] = []
    nao_encontrado: list[str] = []
    for phone in phones:
        contact = db.get_contact_by_phone(phone, canal=WHATSAPP)
        if contact is None:
            nao_encontrado.append(phone)
        elif contact.ia_ativa == activate:
            ja_estava.append(phone)
        else:
            if activate:
                db.reativar_bot(phone, canal=WHATSAPP)
            else:
                db.pausar_bot(phone, canal=WHATSAPP)
            mudou_agora.append(phone)
    return mudou_agora, ja_estava, nao_encontrado


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
• *Ativa o bot 5511999999999, 5511888888888* — funciona com 1 número ou lista
• *Renomeia o Pedro para Pedro Silva*
• *Apaga o contato do 5511999999999* (pede confirmação)
• *Marca a Maria como cliente ativo* / *Confirma venda da Maria*
• *Como está o disparo <lote>?* / *Quantos faltam no <lote>?*

Se houver *duas Marias*, o bot pergunta qual delas (responda *1*, *2* ou o telefone).

*Testar como cliente* (do seu celular admin):
• Envie *teste*, *olá* ou *oi* — o bot simula um cliente e responde aqui
• `#simular 5511999999999 Olá, quero saber os preços`
• `#simular Olá` (usa número de teste padrão)
{warning}
*Automações:*
• Responder um cliente → sai da fila e o bot já volta a responder na hora
• Alertas de fila continuam automáticos
"""


def _format_campaign_status(lote: str, counts: dict) -> str:
    """Portuguese status reply for the `campaign_status` admin command
    (campaign-csv-broadcast) — `counts` is `Database.get_campaign_status`'s
    return, zero-filled for every known status."""
    pendente = counts.get("pendente", 0)
    enviado = counts.get("enviado", 0)
    falha = counts.get("falha", 0)
    pulado = counts.get("pulado", 0)
    total = pendente + enviado + falha + pulado
    if total == 0:
        return f"Não encontrei nenhuma mensagem para o disparo *{lote}*."
    return (
        f"📦 *Disparo {lote}* — {total} mensagem(ns)\n"
        f"Pendente: {pendente}\n"
        f"Enviado: {enviado}\n"
        f"Falha: {falha}\n"
        f"Pulado: {pulado}"
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
            reativar_bot=True,
            assumido_por=admin_phone,
            canal=target.canal,
        ):
            return _reply(
                router,
                db,
                admin_phone,
                contact_id,
                f"✅ *{label}* atendido. Bot já está ativo de novo.",
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

    if acao.startswith("set_tipo_cliente:"):
        # `contact-segmentation-b2b-b2c`: the desired value ("b2b"/"b2c") is
        # encoded in `acao` itself (`f"set_tipo_cliente:{tipo_cliente}"`)
        # rather than added as a new parameter here — `acao` is the only
        # piece of this call that survives a disambiguation round-trip
        # through `admin_sessao` (see `_resolve_set_tipo_cliente` /
        # `_try_pending_disambiguation`), so it is the only place a second
        # value can ride along.
        tipo_cliente = acao.split(":", 1)[1]
        contact = db.get_contact_by_phone(target.external_id, canal=target.canal)
        if not contact:
            return _reply(
                router,
                db,
                admin_phone,
                contact_id,
                f"Contato {label} não encontrado.",
            )
        db.set_contact_tipo_cliente(contact.id, tipo_cliente)
        tipo_label = "empresa (B2B)" if tipo_cliente == "b2b" else "pessoa física (B2C)"
        # No suggestion of an "inverse command" here on purpose — unlike
        # `pause`'s confirmation, there is no obvious single next command,
        # and a made-up one risks the same bug already caught for `pause`
        # (a suggested phrase that silently fails to resolve through
        # `search_contacts_for_admin`'s untokenized substring match). Just
        # confirm what changed.
        return _reply(
            router,
            db,
            admin_phone,
            contact_id,
            f"✅ *{label}* marcado(a) como *{tipo_label}*.",
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

    if acao.startswith("rename:"):
        # `admin-bulk-phone-toggle`: the new name rides along in `acao`
        # itself — same reasoning as `set_tipo_cliente:` above, `acao` is
        # the only piece of this call that survives a disambiguation
        # round-trip through `admin_sessao`.
        new_name = acao.split(":", 1)[1]
        contact = db.get_contact_by_phone(target.external_id, canal=target.canal)
        if not contact:
            return _reply(
                router, db, admin_phone, contact_id, f"Contato {label} não encontrado."
            )
        db.update_contact_push_name(contact.id, new_name)
        return _reply(
            router,
            db,
            admin_phone,
            contact_id,
            f"✅ *{label}* renomeado para *{new_name}*.",
        )

    if acao == "delete_contact":
        # Never deletes here directly — deletion is irreversible
        # (`ON DELETE CASCADE` on `mensagens`/`media_arquivos`), so this
        # only asks for confirmation; the actual `db.delete_contact` call
        # happens in `_try_pending_delete_confirmation` after the admin
        # replies "sim" (`admin-bulk-phone-toggle`, Part D).
        contact = db.get_contact_by_phone(target.external_id, canal=target.canal)
        if not contact:
            return _reply(
                router, db, admin_phone, contact_id, f"Contato {label} não encontrado."
            )
        db.save_admin_sessao(
            admin_phone,
            "confirmar_exclusao",
            [{"external_id": target.external_id, "canal": target.canal, "label": label}],
        )
        return _reply(
            router,
            db,
            admin_phone,
            contact_id,
            f"⚠️ Tem certeza que quer apagar *{label}*? Isso remove TODO o histórico de "
            "mensagens e não pode ser desfeito. Responda *sim* para confirmar ou "
            "qualquer outra coisa para cancelar.",
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


def _try_bulk_phone_toggle(
    query: str,
    activate: bool,
    admin_phone: str,
    db: Database,
    router,
    contact_id: int,
) -> dict | None:
    """Intercepts a pause/reactivate query that names phone(s) directly
    (one or a comma-separated list), applying the idempotent fallback
    (`admin-bulk-phone-toggle`). Returns `None` when the query has no
    recognizable phone at all, so the caller falls back to the existing
    name-based `_resolve_reactivate`/`_resolve_pause` flow unchanged.
    """
    phones = extract_phone_list_from_text(query)
    bulk = phones is not None
    unrecognized = 0
    if bulk:
        total_segments = len([s for s in query.split(",") if s.strip()])
        unrecognized = total_segments - len(phones)
        if not phones:
            return None
    else:
        single = extract_phone_from_text(query)
        if not single:
            return None
        phones = [single]

    changed, already, missing = _toggle_bot_for_phones(phones, activate, db)

    if not bulk:
        # Exactly one phone, no comma in the query — preserve the
        # existing single-target reply wording verbatim (regression:
        # `test_confirmation_message_suggests_a_command_that_actually_
        # reactivates` extracts and re-executes this exact suggestion).
        phone = phones[0]
        if phone in changed:
            if activate:
                text = f"✅ Bot reativado para *{phone}*."
            else:
                text = (
                    f"🔕 Bot pausado para *{phone}*. Envie *reativar {phone}* "
                    "para retomar."
                )
            return _reply(router, db, admin_phone, contact_id, text)
        if phone in already:
            text = (
                f"*{phone}* já está ativo."
                if activate
                else f"*{phone}* já está com o bot pausado."
            )
            return _reply(router, db, admin_phone, contact_id, text)
        # Não encontrado: em vez de só informar, oferece cadastrar
        # (admin-bulk-phone-toggle, Parte B) — ver
        # `_try_pending_contact_creation`.
        db.save_admin_sessao(
            admin_phone,
            "confirmar_criacao",
            [{"phone": phone, "canal": WHATSAPP, "activate": activate}],
        )
        text = (
            f"Não encontrei *{phone}*. Quer cadastrar como novo contato? "
            "Envie o nome (ou *não* para cancelar)."
        )
        return _reply(router, db, admin_phone, contact_id, text)

    # Two or more phones (or one phone + unrecognized segments): grouped
    # PT-BR summary. Missing phones here do NOT trigger the creation flow
    # (would require asking a name per number — out of scope for lists).
    lines: list[str] = []
    if changed:
        emoji = "✅" if activate else "🔕"
        verb = "ativado" if activate else "pausado"
        lines.append(f"{emoji} Bot {verb} para: {', '.join(changed)}")
    if already:
        state = "ativo" if activate else "pausado"
        lines.append(f"Já estava {state}: {', '.join(already)}")
    if missing:
        lines.append(f"Não encontrado: {', '.join(missing)}")
    if unrecognized:
        lines.append(f"Não reconhecido: {unrecognized} número(s) no texto enviado.")
    text = "\n".join(lines) if lines else "Nenhum número reconhecido."
    return _reply(router, db, admin_phone, contact_id, text)


def _resolve_reactivate(
    query: str, admin_phone: str, db: Database
) -> tuple[TargetIdentity | None, str | None]:
    # Direct phone(s) are intercepted earlier by `_try_bulk_phone_toggle`
    # (`admin-bulk-phone-toggle`), which is idempotent — this function only
    # ever sees a query it couldn't resolve to a phone (i.e. name-based).
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
    pausado" reply instead of silently disappearing as "não encontrado".

    Direct phone(s) are intercepted earlier by `_try_bulk_phone_toggle`
    (`admin-bulk-phone-toggle`), which is idempotent — this function only
    ever sees a query it couldn't resolve to a phone (i.e. name-based)."""
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


def _resolve_set_tipo_cliente(
    query: str, tipo_cliente: str, admin_phone: str, db: Database
) -> tuple[TargetIdentity | None, str | None]:
    """Same resolution/disambiguation shape as `_resolve_mark_active_client`
    (no `ia_ativa` filter — any contact, active bot or not, is a valid
    target for a B2B/B2C label, contact-segmentation-b2b-b2c).

    `tipo_cliente` ("b2b"/"b2c") is only needed here to thread it into
    `admin_sessao` when disambiguating (see `_execute_action`'s
    `set_tipo_cliente:` branch for why it rides along in `acao`)."""
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
        db.save_admin_sessao(
            admin_phone, f"set_tipo_cliente:{tipo_cliente}", candidatos
        )
        lines = ["Encontrei vários contatos. Qual deles?"]
        for idx, r in enumerate(rows[:5], start=1):
            name = r["push_name"] or "Sem nome"
            fila = " (na fila)" if r["in_queue"] else ""
            canal = channel_label(r["canal"])
            lines.append(f"*{idx}.* {name} — {r['label']} · {canal}{fila}")
        lines.append("\nResponda com *1*, *2*... ou o telefone.")
        return None, "\n".join(lines)

    return None, f"Não encontrei contato para *{query.strip()}*."


def _resolve_rename(
    query: str, admin_phone: str, db: Database
) -> tuple[TargetIdentity | None, str | None, str | None]:
    """Resolve the target (name or phone) and split off the new name, on
    the literal " para " (`admin-bulk-phone-toggle`, Part C). Same shape
    as `_resolve_mark_active_client`, with `new_name` surviving a possible
    disambiguation round-trip encoded in `acao` (same trick as
    `_resolve_set_tipo_cliente`)."""
    parts = re.split(r"\bpara\b", query, maxsplit=1, flags=re.I)
    if len(parts) != 2 or not parts[1].strip():
        return None, None, "Envie assim: *renomeia <nome ou telefone> para <novo nome>*."
    target_query = parts[0].strip(" :,-–—")
    new_name = parts[1].strip(" :,-–—")
    if not target_query or not new_name:
        return None, None, "Envie assim: *renomeia <nome ou telefone> para <novo nome>*."

    phone = extract_phone_from_text(target_query)
    if phone:
        return TargetIdentity(external_id=phone, canal=WHATSAPP, label=phone), new_name, None

    rows = db.search_contacts_for_admin(target_query)
    if len(rows) == 1:
        r = rows[0]
        return (
            TargetIdentity(
                external_id=r["external_id"] or r["phone"],
                canal=r["canal"],
                label=r["label"],
            ),
            new_name,
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
        db.save_admin_sessao(admin_phone, f"rename:{new_name}", candidatos)
        lines = ["Encontrei vários contatos. Qual deles?"]
        for idx, r in enumerate(rows[:5], start=1):
            name = r["push_name"] or "Sem nome"
            fila = " (na fila)" if r["in_queue"] else ""
            canal = channel_label(r["canal"])
            lines.append(f"*{idx}.* {name} — {r['label']} · {canal}{fila}")
        lines.append("\nResponda com *1*, *2*... ou o telefone.")
        return None, None, "\n".join(lines)

    return None, None, f"Não encontrei contato para *{target_query}*."


def _resolve_delete_contact(
    query: str, admin_phone: str, db: Database
) -> tuple[TargetIdentity | None, str | None]:
    """Same resolution/disambiguation shape as `_resolve_mark_active_client`
    (no `ia_ativa` filter — any contact is a valid deletion target). The
    actual deletion never happens here — `_execute_action`'s
    `delete_contact` branch always asks for confirmation first
    (`admin-bulk-phone-toggle`, Part D)."""
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
        db.save_admin_sessao(admin_phone, "delete_contact", candidatos)
        lines = ["Encontrei vários contatos. Qual deles?"]
        for idx, r in enumerate(rows[:5], start=1):
            name = r["push_name"] or "Sem nome"
            fila = " (na fila)" if r["in_queue"] else ""
            canal = channel_label(r["canal"])
            lines.append(f"*{idx}.* {name} — {r['label']} · {canal}{fila}")
        lines.append("\nResponda com *1*, *2*... ou o telefone.")
        return None, "\n".join(lines)

    return None, f"Não encontrei contato para *{query.strip()}*."


_CANCEL_WORDS = re.compile(r"^(n[aã]o|n|cancelar)$", re.I)


def _try_pending_contact_creation(
    text: str, admin_phone: str, db: Database, router, contact_id: int
) -> dict | None:
    """Second step of the contact-creation flow offered when a single
    phone number isn't found (`admin-bulk-phone-toggle`, Part B). Returns
    `None` without consuming the session when the pending `acao` isn't
    this one — lets `handle_admin_message` move on to other checks (e.g.
    disambiguation).

    If a `confirmar_criacao` session IS pending but `text` looks like a
    real admin command (`parse_admin_intent(text).action != "unknown"`)
    rather than an answer to the "quer cadastrar?" prompt, the pending
    session is cleared (no point insisting later) and `None` is returned
    so `handle_admin_message` processes `text` as that command instead —
    unlike `_try_pending_disambiguation`, which leaves its session intact
    on an unrecognized reply, since there the ambiguity is about *which*
    candidate, not whether the reply is a command at all."""
    pending = db.get_admin_sessao(admin_phone)
    if not pending:
        return None
    acao, candidatos = pending
    if acao != "confirmar_criacao" or not candidatos:
        return None
    alvo = candidatos[0]
    raw = text.strip()
    if _CANCEL_WORDS.match(raw):
        db.clear_admin_sessao(admin_phone)
        return _reply(router, db, admin_phone, contact_id, "Ok, não criei o contato.")
    if not raw:
        db.clear_admin_sessao(admin_phone)
        return _reply(router, db, admin_phone, contact_id, "Ok, não criei o contato.")
    if parse_admin_intent(raw).action != "unknown":
        # The admin sent something that looks like a real command instead
        # of answering the "quer cadastrar?" prompt (e.g. a follow-up
        # command sent while the prompt was still pending). Abandon the
        # pending creation — insisting on the old prompt after the admin
        # has moved on would be more confusing than useful — and let
        # `handle_admin_message` process `text` as a normal command via
        # `parse_admin_intent` right after this call returns `None`.
        db.clear_admin_sessao(admin_phone)
        return None
    db.clear_admin_sessao(admin_phone)
    db.create_contact(phone=alvo["phone"], push_name=raw, ia_ativa=alvo["activate"])
    estado = "ativo" if alvo["activate"] else "pausado"
    return _reply(
        router,
        db,
        admin_phone,
        contact_id,
        f"✅ Contato *{raw}* ({alvo['phone']}) criado, bot já {estado}.",
    )


_CONFIRM_YES = re.compile(r"^(sim|s|confirmar|confirmo|yes)$", re.I)


def _try_pending_delete_confirmation(
    text: str, admin_phone: str, db: Database, router, contact_id: int
) -> dict | None:
    """Second step (confirmation) of the contact-deletion command
    (`admin-bulk-phone-toggle`, Part D). Returns `None` without consuming
    the session when the pending `acao` isn't this one.

    Same design pattern as `_try_pending_contact_creation`: an affirmative
    reply confirms and deletes, but anything else is only treated as an
    explicit refusal if it doesn't look like a real admin command first —
    otherwise the pending session is dropped (no deletion) and `None` is
    returned so `handle_admin_message` processes `text` as that command."""
    pending = db.get_admin_sessao(admin_phone)
    if not pending:
        return None
    acao, candidatos = pending
    if acao != "confirmar_exclusao" or not candidatos:
        return None
    alvo = candidatos[0]
    if _CONFIRM_YES.match(text.strip()):
        db.clear_admin_sessao(admin_phone)
    elif parse_admin_intent(text.strip()).action != "unknown":
        # Admin sent a real command instead of answering the delete
        # confirmation prompt — abandon the pending deletion and let
        # `handle_admin_message` process `text` normally right after this
        # call returns `None`.
        db.clear_admin_sessao(admin_phone)
        return None
    else:
        db.clear_admin_sessao(admin_phone)
        return _reply(router, db, admin_phone, contact_id, "Cancelado. Nada foi apagado.")
    ok = db.delete_contact(alvo["external_id"], canal=alvo["canal"])
    if ok:
        return _reply(
            router,
            db,
            admin_phone,
            contact_id,
            f"🗑️ Contato *{alvo['label']}* apagado, junto com todo o histórico.",
        )
    return _reply(router, db, admin_phone, contact_id, "Não encontrei mais esse contato.")


def handle_admin_message(
    phone: str,
    text: str,
    db: Database,
    router,
    contact_id: int,
) -> dict:
    admin_phone = normalize_phone(phone)
    db.save_message(contact_id, direction="in", text=text)

    pending_delete = _try_pending_delete_confirmation(
        text, admin_phone, db, router, contact_id
    )
    if pending_delete:
        return pending_delete

    pending_create = _try_pending_contact_creation(
        text, admin_phone, db, router, contact_id
    )
    if pending_create:
        return pending_create

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

    if intent.action == "campaign_status" and intent.query:
        counts = db.get_campaign_status(intent.query.strip())
        return _reply(
            router,
            db,
            admin_phone,
            contact_id,
            _format_campaign_status(intent.query.strip(), counts),
        )

    if intent.action == "complete_all":
        count = db.mark_all_attended(
            reativar_bot=True,
            assumido_por=admin_phone,
        )
        return _reply(
            router,
            db,
            admin_phone,
            contact_id,
            f"✅ {count} contato(s) atendidos. Bots já estão ativos de novo.",
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
        bulk = _try_bulk_phone_toggle(
            intent.query, True, admin_phone, db, router, contact_id
        )
        if bulk:
            return bulk
        target, err = _resolve_reactivate(intent.query, admin_phone, db)
        if err:
            return _reply(router, db, admin_phone, contact_id, err)
        return _execute_action(
            "reactivate", target, admin_phone, db, router, contact_id
        )

    if intent.action == "pause" and intent.query:
        bulk = _try_bulk_phone_toggle(
            intent.query, False, admin_phone, db, router, contact_id
        )
        if bulk:
            return bulk
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

    if intent.action == "set_tipo_cliente" and intent.query and intent.tipo_cliente:
        target, err = _resolve_set_tipo_cliente(
            intent.query, intent.tipo_cliente, admin_phone, db
        )
        if err:
            return _reply(router, db, admin_phone, contact_id, err)
        return _execute_action(
            f"set_tipo_cliente:{intent.tipo_cliente}",
            target,
            admin_phone,
            db,
            router,
            contact_id,
        )

    if intent.action == "rename" and intent.query:
        target, new_name, err = _resolve_rename(intent.query, admin_phone, db)
        if err:
            return _reply(router, db, admin_phone, contact_id, err)
        return _execute_action(
            f"rename:{new_name}", target, admin_phone, db, router, contact_id
        )

    if intent.action == "delete_contact" and intent.query:
        target, err = _resolve_delete_contact(intent.query, admin_phone, db)
        if err:
            return _reply(router, db, admin_phone, contact_id, err)
        return _execute_action(
            "delete_contact", target, admin_phone, db, router, contact_id
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
