"""Shared in-memory fakes for the test suite.

The suite is plain `unittest` (`make test` runs `unittest discover`), so these
live in an importable module rather than a pytest `conftest.py`.

`FakeDatabase` mirrors the public surface of `whatbot.db.Database` with
dictionaries instead of SQL, returning the same dataclasses production code
already expects. It exists so the domain modules — which are otherwise reachable
only with a live Postgres — can be exercised end to end.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import re
import unicodedata

from whatbot.channels import WHATSAPP, normalize_channel
from whatbot.db import (
    CAMPAIGN_MESSAGE_STATUSES,
    CONTACT_STATUSES,
    CONTACT_TIPO_CLIENTES,
    CampaignMessage,
    ChannelCredential,
    Contact,
    MessageRecord,
    WaitingContact,
    resolve_label,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fold(text: str) -> str:
    """Accent-fold + lowercase, mirroring `whatbot.contact_resolver._fold`.

    Used by `FakeDatabase.search_contacts_for_admin` on *both* sides of the
    comparison — the query term and the stored `push_name`/`handle` — to
    mirror `Database.search_contacts_for_admin`'s `unaccent(push_name)` on
    the real Postgres side. Folding only the query term (as the buggy
    version did) misses a stored "João" when the admin types "Joao".
    """
    folded = unicodedata.normalize("NFKD", text.lower())
    return folded.encode("ascii", "ignore").decode("ascii")


class FakeClient:
    """Minimal channel client that records what it was asked to send."""

    def __init__(self, canal: str):
        self.canal = canal
        self.sent: list[dict] = []
        # When set, `send_text` raises this instead of recording the send —
        # lets tests simulate a channel-level refusal (e.g. `ChannelError`
        # with `cause="window_expired"`) without a real client.
        self.raise_error: Exception | None = None
        # conversation-history-media-storage: `None` by default (most
        # clients/tests never touch media) — a test opts in by assigning a
        # callable `(media_id) -> (bytes, mime_type)` here, or one that
        # raises to simulate a download failure.
        self.download_media = None

    def send_text(
        self,
        to,
        text,
        *,
        source="bot",
        contact_id=None,
        simulated=False,
        human_agent=False,
    ):
        if self.raise_error is not None:
            raise self.raise_error
        self.sent.append(
            {
                "to": to,
                "text": text,
                "source": source,
                "contact_id": contact_id,
                "simulated": simulated,
                "human_agent": human_agent,
            }
        )
        return {"ok": True, "canal": self.canal}


class LegacyClient:
    """Client without the `human_agent` kwarg, as third-party/older code may be."""

    canal = WHATSAPP

    def __init__(self):
        self.sent: list[tuple] = []

    def send_text(self, to, text, *, source="bot", contact_id=None, simulated=False):
        self.sent.append((to, text, source))
        return {"ok": True}


class DuckRouter:
    """Routes by channel without being a `ChannelRouter` instance.

    Guards against dispatch helpers that check concrete type instead of
    capability, which would silently drop `canal` and `human_agent`.
    """

    def __init__(self, clients):
        self._clients = {c.canal: c for c in clients}
        self.admin_channel = WHATSAPP

    def send_text(
        self,
        to,
        text,
        *,
        canal=None,
        source="bot",
        contact_id=None,
        simulated=False,
        human_agent=False,
    ):
        client = self._clients[canal or WHATSAPP]
        return client.send_text(
            to,
            text,
            source=source,
            contact_id=contact_id,
            simulated=simulated,
            human_agent=human_agent,
        )

    def send_admin_text(
        self, to, text, *, source="admin", contact_id=None, simulated=False
    ):
        return self.send_text(
            to,
            text,
            canal=self.admin_channel,
            source=source,
            contact_id=contact_id,
            simulated=simulated,
        )


class FakeLlm:
    """Stands in for the LLM client, with a switch for the unavailable path."""

    def __init__(self, reply: str = "Resposta do modelo.", unavailable: bool = False):
        self.reply = reply
        self.unavailable = unavailable
        self.calls: list[dict] = []

    def chat(self, system_prompt: str, recent_history, user_message: str, **kwargs):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "recent_history": recent_history,
                "user_message": user_message,
            }
        )
        if self.unavailable:
            from whatbot.llm import LlmUnavailableError

            raise LlmUnavailableError("fake: modelo indisponível")
        return self.reply


class FakeDatabase:
    """In-memory stand-in for `whatbot.db.Database`.

    Contacts are dicts keyed by id, mirroring the `contatos` columns the
    production queries touch. Only behaviour the domain code depends on is
    reproduced: waiting-queue filtering, handover archival, batch counting and
    scheduled reactivation.
    """

    def __init__(self):
        self.contacts: Dict[int, dict] = {}
        self.messages: List[dict] = []
        self.handover_historico: List[dict] = []
        self.admin_sessoes: Dict[str, dict] = {}
        self.daily_summary_sent: set = set()
        self.batch_pending = 0
        self._next_contact_id = 1
        self._next_message_id = 1
        self.schema_ensured = False
        # instagram-ingestion-service: mirrors `webhook_eventos` / `canal_credenciais`.
        self.webhook_events: Dict[tuple, datetime] = {}
        self.channel_credentials: Dict[str, dict] = {}
        # Mirrors `canal_envio_falhas` (critic BLOQUEADOR 1: persisted streak).
        self.send_fail_streaks: Dict[str, int] = {}
        # Mirrors `produtos_catalogo` (catalog-product-sync).
        self.catalog_products: Dict[str, dict] = {}
        # Mirrors `disparo_mensagens` (campaign-csv-broadcast).
        self.campaign_messages: Dict[int, dict] = {}
        self._next_campaign_message_id = 1
        # Mirrors `media_arquivos` (conversation-history-media-storage).
        self.media_files: Dict[int, dict] = {}
        self._next_media_id = 1

    # -- infra -----------------------------------------------------------

    def init_pool(self) -> None:  # pragma: no cover - nothing to pool
        pass

    def close(self) -> None:  # pragma: no cover - nothing to close
        pass

    def ensure_schema(self) -> None:
        self.schema_ensured = True

    # -- helpers ---------------------------------------------------------

    def _row_to_contact(self, row: dict) -> Contact:
        return Contact(
            id=row["id"],
            phone=row["phone"],
            status=row["status"],
            ia_ativa=row["ia_ativa"],
            created_at=row["created_at"],
            push_name=row["push_name"],
            handover_at=row["handover_at"],
            atendido_at=row["atendido_at"],
            handover_motivo=row["handover_motivo"],
            session_state=row["session_state"],
            canal=row["canal"],
            external_id=row["external_id"],
            handle=row["handle"],
            tipo_cliente=row.get("tipo_cliente", "b2c"),
        )

    def _row_to_waiting(self, row: dict) -> WaitingContact:
        elapsed = (_now() - row["handover_at"]).total_seconds() / 60
        return WaitingContact(
            id=row["id"],
            phone=row["phone"],
            push_name=row["push_name"],
            handover_at=row["handover_at"],
            handover_motivo=row["handover_motivo"],
            minutes_waiting=int(elapsed),
            prioridade=int(row["prioridade"] or 0),
            assumido_por=row["assumido_por"],
            canal=row["canal"],
            external_id=row["external_id"],
            handle=row["handle"],
            last_inbound_at=row.get("last_inbound_at"),
            # handover-summary-for-agent: mirrors the `status`/`session_state`
            # columns `Database._row_to_waiting` now selects.
            status=row.get("status"),
            session_state=dict(row.get("session_state") or {}),
        )

    def _is_waiting_row(self, row: dict) -> bool:
        return row["handover_at"] is not None and row["atendido_at"] is None

    def _find_by_identity(self, external_id: str, canal: str | None = None) -> Optional[dict]:
        canal = normalize_channel(canal)
        for row in self.contacts.values():
            if row["canal"] == canal and row["external_id"] == external_id:
                return row
        return None

    # -- contacts --------------------------------------------------------

    def get_contact_by_phone(self, phone: str, canal: str | None = None) -> Optional[Contact]:
        row = self._find_by_identity(phone, canal)
        return self._row_to_contact(row) if row else None

    def create_contact(
        self,
        phone: str | None = None,
        status: str = "novo_lead",
        ia_ativa: bool = True,
        push_name: str | None = None,
        *,
        canal: str | None = None,
        external_id: str | None = None,
        handle: str | None = None,
    ) -> Contact:
        canal = normalize_channel(canal)
        external_id = external_id or phone
        if not external_id:
            raise ValueError("create_contact requer external_id (ou phone para whatsapp)")
        stored_phone = external_id if canal == WHATSAPP else None
        contact_id = self._next_contact_id
        self._next_contact_id += 1
        row = {
            "id": contact_id,
            "phone": stored_phone,
            "status": status,
            "ia_ativa": ia_ativa,
            "created_at": _now(),
            "push_name": push_name,
            "handover_at": None,
            "atendido_at": None,
            "handover_motivo": None,
            "long_wait_notified": False,
            "prioridade": 0,
            "assumido_por": None,
            "bot_resume_at": None,
            "session_state": {},
            "canal": canal,
            "external_id": external_id,
            "handle": handle,
            "last_inbound_at": None,
            "tipo_cliente": "b2c",
        }
        self.contacts[contact_id] = row
        return self._row_to_contact(row)

    def update_contact_push_name(self, contact_id: int, push_name: str | None) -> None:
        if not push_name:
            return
        self.contacts[contact_id]["push_name"] = push_name

    def update_contact_session_state(
        self, contact_id: int, session_state: dict[str, Any]
    ) -> None:
        self.contacts[contact_id]["session_state"] = dict(session_state)

    def update_contact_ia_active(self, contact_id: int, ia_ativa: bool) -> None:
        self.contacts[contact_id]["ia_ativa"] = ia_ativa

    def set_contact_status(self, contact_id: int, status: str) -> None:
        if status not in CONTACT_STATUSES:
            raise ValueError(
                f"status inválido: {status!r} (esperado um de {sorted(CONTACT_STATUSES)})"
            )
        self.contacts[contact_id]["status"] = status

    def set_contact_tipo_cliente(self, contact_id: int, tipo_cliente: str) -> None:
        if tipo_cliente not in CONTACT_TIPO_CLIENTES:
            raise ValueError(
                f"tipo_cliente inválido: {tipo_cliente!r} "
                f"(esperado um de {sorted(CONTACT_TIPO_CLIENTES)})"
            )
        self.contacts[contact_id]["tipo_cliente"] = tipo_cliente

    def update_contact_last_inbound(
        self, contact_id: int, when: datetime | None = None
    ) -> None:
        self.contacts[contact_id]["last_inbound_at"] = when or _now()

    def get_last_inbound_at(self, external_id: str, *, canal: str) -> Optional[datetime]:
        row = self._find_by_identity(external_id, canal)
        return row["last_inbound_at"] if row else None

    # -- handover / queue ------------------------------------------------

    def enroll_handover(
        self,
        contact_id: int,
        motivo: str,
        push_name: str | None = None,
        prioridade: int = 0,
    ) -> None:
        row = self.contacts[contact_id]
        row.update(
            {
                "ia_ativa": False,
                "handover_at": _now(),
                "atendido_at": None,
                "handover_motivo": motivo,
                "long_wait_notified": False,
                "prioridade": prioridade,
                "assumido_por": None,
            }
        )
        if push_name:
            row["push_name"] = push_name

    def assumir_atendimento_direto(
        self,
        contact_id: int,
        *,
        motivo: str = "assumido_via_painel",
        assumido_por: str | None = None,
        prioridade: int = 0,
    ) -> None:
        row = self.contacts[contact_id]
        row.update(
            {
                "ia_ativa": False,
                "handover_at": _now(),
                "atendido_at": None,
                "handover_motivo": motivo,
                "long_wait_notified": False,
                "prioridade": prioridade,
                "assumido_por": assumido_por,
            }
        )

    def is_waiting(self, phone: str, canal: str | None = None) -> bool:
        row = self._find_by_identity(phone, canal)
        return bool(row and self._is_waiting_row(row))

    def get_waiting_contacts(self) -> List[WaitingContact]:
        waiting = [r for r in self.contacts.values() if self._is_waiting_row(r)]
        waiting.sort(key=lambda r: (-int(r["prioridade"] or 0), r["handover_at"]))
        return [self._row_to_waiting(r) for r in waiting]

    def get_contact_waiting(self, phone: str, canal: str | None = None) -> WaitingContact | None:
        row = self._find_by_identity(phone, canal)
        if row and self._is_waiting_row(row):
            return self._row_to_waiting(row)
        return None

    def get_long_waiting_contacts(self, min_minutes: int) -> List[WaitingContact]:
        return [
            c for c in self.get_waiting_contacts() if c.minutes_waiting >= min_minutes
        ]

    def get_long_wait_unnotified(self, min_minutes: int) -> List[WaitingContact]:
        rows = [
            r
            for r in self.contacts.values()
            if self._is_waiting_row(r)
            and not r["long_wait_notified"]
            and (_now() - r["handover_at"]).total_seconds() / 60 >= min_minutes
        ]
        rows.sort(key=lambda r: (-int(r["prioridade"] or 0), r["handover_at"]))
        return [self._row_to_waiting(r) for r in rows]

    def mark_long_wait_notified(self, contact_ids: List[int]) -> None:
        for contact_id in contact_ids:
            if contact_id in self.contacts:
                self.contacts[contact_id]["long_wait_notified"] = True

    def increment_handover_batch(self) -> int:
        self.batch_pending += 1
        return self.batch_pending

    def reset_handover_batch(self) -> None:
        self.batch_pending = 0

    def _archive_handover(self, row: dict, assumido_por: str | None) -> None:
        if row["handover_at"] is None:
            return
        wait_minutes = int((_now() - row["handover_at"]).total_seconds() / 60)
        self.handover_historico.append(
            {
                "contact_id": row["id"],
                "phone": row["phone"],
                "push_name": row["push_name"],
                "handover_at": row["handover_at"],
                "atendido_at": _now(),
                "wait_minutes": wait_minutes,
                "prioridade": int(row["prioridade"] or 0),
                "assumido_por": assumido_por,
                "motivo": row["handover_motivo"],
                "canal": row["canal"],
                "external_id": row["external_id"],
            }
        )

    def mark_attended(
        self,
        phone: str,
        reativar_bot: bool = False,
        assumido_por: str | None = None,
        schedule_resume_hours: int | None = None,
        *,
        canal: str | None = None,
    ) -> bool:
        row = self._find_by_identity(phone, canal)
        if not row or not self._is_waiting_row(row):
            return False
        self._archive_handover(row, assumido_por)

        if reativar_bot:
            resume_at, ia_ativa = None, True
        elif schedule_resume_hours is not None:
            resume_at = _now() + timedelta(hours=int(schedule_resume_hours))
            ia_ativa = False
        else:
            resume_at, ia_ativa = None, False

        row.update(
            {
                "atendido_at": _now(),
                "ia_ativa": ia_ativa,
                "handover_at": None,
                "handover_motivo": None,
                "long_wait_notified": False,
                "prioridade": 0,
                "assumido_por": None,
                "bot_resume_at": resume_at,
            }
        )
        return True

    def mark_all_attended(
        self,
        reativar_bot: bool = False,
        assumido_por: str | None = None,
        schedule_resume_hours: int | None = None,
    ) -> int:
        count = 0
        for contact in self.get_waiting_contacts():
            if self.mark_attended(
                contact.external_id,
                reativar_bot=reativar_bot,
                assumido_por=assumido_por,
                schedule_resume_hours=schedule_resume_hours,
                canal=contact.canal,
            ):
                count += 1
        return count

    def assumir_contato(
        self, phone: str, admin_phone: str, *, canal: str | None = None
    ) -> WaitingContact | None:
        row = self._find_by_identity(phone, canal)
        if not row or not self._is_waiting_row(row):
            return None
        row["assumido_por"] = admin_phone
        return self._row_to_waiting(row)

    def reativar_bot(self, phone: str, *, canal: str | None = None) -> bool:
        row = self._find_by_identity(phone, canal)
        if not row:
            return False
        row.update(
            {
                "ia_ativa": True,
                "atendido_at": row["atendido_at"] or _now(),
                "handover_at": None,
                "handover_motivo": None,
                "long_wait_notified": False,
                "prioridade": 0,
                "assumido_por": None,
                "bot_resume_at": None,
            }
        )
        return True

    def pausar_bot(self, phone: str, *, canal: str | None = None) -> bool:
        """Mirrors `Database.pausar_bot` (admin-bot-pause): only flips
        `ia_ativa`, leaves `bot_resume_at` untouched."""
        row = self._find_by_identity(phone, canal)
        if not row:
            return False
        row["ia_ativa"] = False
        return True

    def process_auto_reactivations(self) -> list[str]:
        """Mirrors `Database.process_auto_reactivations`: returns labels, not
        raw `phone` (which is `None` for non-WhatsApp contacts)."""
        reactivated = []
        for row in self.contacts.values():
            resume_at = row["bot_resume_at"]
            if not row["ia_ativa"] and resume_at is not None and resume_at <= _now():
                row["ia_ativa"] = True
                row["bot_resume_at"] = None
                label = resolve_label(
                    row["push_name"], row["handle"], row["external_id"] or row["phone"]
                )
                reactivated.append(label)
        return reactivated

    # -- stats -----------------------------------------------------------

    def get_daily_handover_stats(self, day) -> dict:
        same_day = [
            h for h in self.handover_historico if h["atendido_at"].date() == day
        ]
        total = len(same_day)
        avg_wait = (
            sum(h["wait_minutes"] for h in same_day) / total if total else 0
        )
        return {
            "atendidos": total,
            "avg_wait_minutes": int(avg_wait),
            "alta_prioridade": len([h for h in same_day if h["prioridade"] >= 1]),
            "still_waiting": len(self.get_waiting_contacts()),
        }

    def count_handovers_today(self, day) -> int:
        archived = len(
            [h for h in self.handover_historico if h["handover_at"].date() == day]
        )
        current = len(
            [
                r
                for r in self.contacts.values()
                if r["handover_at"] is not None and r["handover_at"].date() == day
            ]
        )
        return archived + current

    def was_daily_summary_sent(self, day) -> bool:
        return day in self.daily_summary_sent

    def mark_daily_summary_sent(self, day) -> None:
        self.daily_summary_sent.add(day)

    # -- messages --------------------------------------------------------

    def save_message(
        self,
        contact_id: int,
        direction: str,
        text: str,
        *,
        canal: str | None = None,
        message_id: str | None = None,
        payload: dict | None = None,
        media_id: int | None = None,
    ) -> None:
        # Mirrors the real `mensagens_canal_message_id_idx` partial unique
        # index (`whatbot/db.py::ensure_schema()`): a re-delivered
        # `(canal, message_id)` is a silent no-op, not a duplicate row.
        if message_id is not None and any(
            m.get("canal") == canal and m.get("message_id") == message_id
            for m in self.messages
        ):
            return
        self.messages.append(
            {
                "id": self._next_message_id,
                "contact_id": contact_id,
                "direction": direction,
                "text": text,
                "created_at": _now(),
                "canal": canal,
                "message_id": message_id,
                "payload": payload,
                "media_id": media_id,
            }
        )
        self._next_message_id += 1

    def _row_to_fake_message(self, m: dict) -> MessageRecord:
        return MessageRecord(
            id=m["id"],
            contact_id=m["contact_id"],
            direction=m["direction"],
            text=m["text"],
            created_at=m["created_at"],
            canal=m.get("canal"),
            message_id=m.get("message_id"),
            payload=m.get("payload"),
            media_id=m.get("media_id"),
        )

    def get_recent_messages(
        self, contact_id: int, limit: int = 10
    ) -> List[MessageRecord]:
        rows = [m for m in self.messages if m["contact_id"] == contact_id]
        rows.sort(key=lambda m: (m["created_at"], m["id"]), reverse=True)
        return [self._row_to_fake_message(m) for m in rows[:limit]]

    def get_conversation(
        self, contact_id: int, *, limit: int = 50, before: int | None = None
    ) -> List[MessageRecord]:
        rows = [m for m in self.messages if m["contact_id"] == contact_id]
        if before is not None:
            rows = [m for m in rows if m["id"] < before]
        rows.sort(key=lambda m: (m["created_at"], m["id"]), reverse=True)
        return [self._row_to_fake_message(m) for m in rows[:limit]]

    # -- media_arquivos (conversation-history-media-storage) -------------

    def insert_media_file(
        self,
        *,
        contact_id: int | None,
        canal: str,
        tipo: str,
        storage_key: str,
        status: str = "baixado",
        mime_type: str | None = None,
        tamanho_bytes: int | None = None,
        storage_backend: str = "local",
        origem_media_id: str | None = None,
        erro: str | None = None,
    ) -> int:
        media_id = self._next_media_id
        self._next_media_id += 1
        self.media_files[media_id] = {
            "id": media_id,
            "contact_id": contact_id,
            "canal": canal,
            "tipo": tipo,
            "mime_type": mime_type,
            "tamanho_bytes": tamanho_bytes,
            "storage_backend": storage_backend,
            "storage_key": storage_key,
            "origem_media_id": origem_media_id,
            "status": status,
            "erro": erro,
            "created_at": _now(),
        }
        return media_id

    def get_media_file(self, media_id: int):
        from whatbot.db import MediaFile

        row = self.media_files.get(media_id)
        if row is None:
            return None
        return MediaFile(**row)

    def get_contact_by_id(self, contact_id: int) -> Optional[Contact]:
        row = self.contacts.get(contact_id)
        return self._row_to_contact(row) if row else None

    def list_conversations(self, *, limit: int = 50) -> List[dict]:
        by_contact: dict[int, dict] = {}
        for m in sorted(self.messages, key=lambda m: (m["created_at"], m["id"])):
            by_contact[m["contact_id"]] = m
        conversas = []
        for contact_id, last in by_contact.items():
            contact = self.get_contact_by_id(contact_id)
            if contact is None:
                continue
            conversas.append(
                {
                    "contact_id": contact_id,
                    "canal": contact.canal,
                    "external_id": contact.external_id,
                    "label": contact.label,
                    "status": contact.status,
                    "ia_ativa": contact.ia_ativa,
                    "ultima_mensagem": last["text"],
                    "ultima_direcao": last["direction"],
                    "ultima_mensagem_em": last["created_at"],
                }
            )
        conversas.sort(key=lambda c: c["ultima_mensagem_em"], reverse=True)
        return conversas[:limit]

    # -- admin sessions --------------------------------------------------

    def save_admin_sessao(
        self, admin_phone: str, acao: str, candidatos: list[dict]
    ) -> None:
        self.admin_sessoes[admin_phone] = {
            "acao": acao,
            "candidatos": list(candidatos),
            "created_at": _now(),
        }

    def get_admin_sessao(self, admin_phone: str) -> tuple[str, list[dict]] | None:
        sessao = self.admin_sessoes.get(admin_phone)
        if not sessao:
            return None
        if _now() - sessao["created_at"] > timedelta(minutes=10):
            return None
        return sessao["acao"], sessao["candidatos"]

    def clear_admin_sessao(self, admin_phone: str) -> None:
        self.admin_sessoes.pop(admin_phone, None)

    def search_contacts_for_admin(self, query: str) -> list[dict]:
        phone = re.sub(r"\D", "", query)
        if phone and len(phone) >= 8:
            # Mirrors `Database.search_contacts_for_admin`: also match
            # `external_id` directly, since non-WhatsApp contacts never
            # populate `phone` (see design.md, Decisão 3).
            matches = [
                r
                for r in self.contacts.values()
                if (r["phone"] and phone[-8:] in r["phone"])
                or (r["external_id"] and phone[-8:] in r["external_id"])
            ]
        else:
            term = _fold(query)
            matches = [
                r
                for r in self.contacts.values()
                if term
                and (
                    term in _fold(r["push_name"] or "")
                    or term in _fold(r["handle"] or "")
                )
            ]
        matches.sort(key=lambda r: r["created_at"], reverse=True)
        return [
            {
                "id": r["id"],
                "phone": r["phone"],
                "push_name": r["push_name"],
                "ia_ativa": r["ia_ativa"],
                "in_queue": self._is_waiting_row(r),
                "canal": r["canal"],
                "external_id": r["external_id"],
                "handle": r["handle"],
                "tipo_cliente": r.get("tipo_cliente", "b2c"),
                "label": resolve_label(r["push_name"], r["handle"], r["external_id"] or r["phone"]),
            }
            for r in matches[:5]
        ]

    # -- webhook idempotency ----------------------------------------------

    def record_webhook_event(self, canal: str, message_id: str) -> bool:
        canal = normalize_channel(canal)
        key = (canal, message_id)
        if key in self.webhook_events:
            return False
        self.webhook_events[key] = _now()
        return True

    def get_last_webhook_event_at(self, canal: str | None = None) -> Optional[datetime]:
        canal = normalize_channel(canal)
        times = [t for (c, _mid), t in self.webhook_events.items() if c == canal]
        return max(times) if times else None

    def purge_old_webhook_events(self, older_than_days: int = 7) -> int:
        cutoff = _now() - timedelta(days=older_than_days)
        stale = [k for k, t in self.webhook_events.items() if t < cutoff]
        for k in stale:
            del self.webhook_events[k]
        return len(stale)

    def delete_webhook_event(self, canal: str, message_id: str) -> None:
        canal = normalize_channel(canal)
        self.webhook_events.pop((canal, message_id), None)

    # -- send-failure streak ----------------------------------------------

    def increment_send_fail_streak(self, canal: str) -> int:
        canal = normalize_channel(canal)
        self.send_fail_streaks[canal] = self.send_fail_streaks.get(canal, 0) + 1
        return self.send_fail_streaks[canal]

    def reset_send_fail_streak(self, canal: str) -> None:
        canal = normalize_channel(canal)
        self.send_fail_streaks[canal] = 0

    # -- channel credentials ------------------------------------------------

    def upsert_channel_credential(
        self,
        canal: str,
        access_token: str,
        *,
        account_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        canal = normalize_channel(canal)
        self.channel_credentials[canal] = {
            "canal": canal,
            "account_id": account_id,
            "access_token": access_token,
            "expires_at": expires_at,
            "refreshed_at": _now(),
        }

    def get_channel_credential(self, canal: str) -> Optional[ChannelCredential]:
        canal = normalize_channel(canal)
        row = self.channel_credentials.get(canal)
        if not row:
            return None
        return ChannelCredential(**row)

    # -- product catalog cache (catalog-product-sync) ---------------------

    def upsert_catalog_products(self, products: List[dict]) -> None:
        for product in products:
            product_id = product["product_id"]
            self.catalog_products[product_id] = {
                "product_id": product_id,
                "nome": product.get("nome"),
                "preco": product.get("preco"),
                "disponivel": product.get("disponivel"),
                "last_synced_at": _now(),
            }

    def resolve_catalog_items(self, product_ids: List[str]) -> List[dict]:
        return [
            dict(self.catalog_products[pid])
            for pid in product_ids
            if pid in self.catalog_products
        ]

    # -- mass-broadcast campaign queue (campaign-csv-broadcast) -----------

    def _row_to_campaign_message(self, row: dict) -> CampaignMessage:
        return CampaignMessage(
            id=row["id"],
            lote=row["lote"],
            canal=row["canal"],
            external_id=row["external_id"],
            mensagem=row["mensagem"],
            status=row["status"],
            tentativas=row["tentativas"],
            erro=row["erro"],
            criado_em=row["criado_em"],
            enviado_em=row["enviado_em"],
        )

    def insert_campaign_message(
        self, lote: str, canal: str, external_id: str, mensagem: str
    ) -> int:
        message_id = self._next_campaign_message_id
        self._next_campaign_message_id += 1
        self.campaign_messages[message_id] = {
            "id": message_id,
            "lote": lote,
            "canal": normalize_channel(canal),
            "external_id": external_id,
            "mensagem": mensagem,
            "status": "pendente",
            "tentativas": 0,
            "erro": None,
            "criado_em": _now(),
            "enviado_em": None,
        }
        return message_id

    def get_pending_campaign_messages(self, limit: int) -> List[CampaignMessage]:
        pending = [
            r for r in self.campaign_messages.values() if r["status"] == "pendente"
        ]
        pending.sort(key=lambda r: (r["criado_em"], r["id"]))
        return [self._row_to_campaign_message(r) for r in pending[:limit]]

    def mark_campaign_message_sent(self, message_id: int) -> None:
        row = self.campaign_messages[message_id]
        row["status"] = "enviado"
        row["enviado_em"] = _now()

    def mark_campaign_message_retry(
        self, message_id: int, tentativas: int, erro: str
    ) -> None:
        row = self.campaign_messages[message_id]
        row["tentativas"] = tentativas
        row["erro"] = erro

    def mark_campaign_message_failed(self, message_id: int, erro: str) -> None:
        row = self.campaign_messages[message_id]
        row["status"] = "falha"
        row["erro"] = erro

    def mark_campaign_message_skipped(self, message_id: int) -> None:
        self.campaign_messages[message_id]["status"] = "pulado"

    def get_campaign_status(self, lote: str) -> dict:
        counts = {status: 0 for status in CAMPAIGN_MESSAGE_STATUSES}
        for row in self.campaign_messages.values():
            if row["lote"] == lote:
                counts[row["status"]] = counts.get(row["status"], 0) + 1
        return counts
