"""Database layer: Postgres helpers using psycopg and psycopg_pool."""

from __future__ import annotations

from typing import Any, Optional, List
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg_pool import ConnectionPool

from .channels.base import WHATSAPP, normalize_channel


def resolve_label(
    name: str | None, handle: str | None, external_id: str | None
) -> str:
    """Precedence for a human-readable identity: name -> channel handle -> raw id.

    Pure, no I/O — safe for any consumer (queue, notifications, logs). This is
    the single source of truth for the precedence order (see design.md,
    Decisão 8 / requirement "Rótulo legível de contato"); other modules
    (`contact_resolver.py`, `queue.py`) must call this instead of
    reimplementing the precedence locally.
    """
    return name or handle or external_id or ""


# Closed set of `contatos.status` values (contact-interest-memory). Validated
# in Python by `Database.set_contact_status`/`create_contact`'s caller-supplied
# default — no DB `CHECK` constraint, same style as other setters in this
# module (see `update_contact_ia_active`).
CONTACT_STATUSES = {
    "novo_lead",
    "interessado",
    "comprando",
    "cliente_ativo",
    "cancelado",
}

# Closed set of `contatos.tipo_cliente` values (contact-segmentation-b2b-b2c).
# Validated in Python by `Database.set_contact_tipo_cliente` — same style as
# `CONTACT_STATUSES` above, no DB `CHECK` constraint (see design.md,
# Decisão 1).
CONTACT_TIPO_CLIENTES = {"b2c", "b2b"}

# Closed set of `disparo_mensagens.status` values (campaign-csv-broadcast).
# Same style as `CONTACT_STATUSES`/`CONTACT_TIPO_CLIENTES` — no DB `CHECK`
# constraint, transitions are enforced by the Python call sites
# (`whatbot.main.send_campaign_queue`), not by the schema itself.
CAMPAIGN_MESSAGE_STATUSES = {"pendente", "enviado", "falha", "pulado"}


@dataclass
class Contact:
    id: int
    phone: str | None
    status: str
    ia_ativa: bool
    created_at: datetime
    push_name: str | None = None
    handover_at: datetime | None = None
    atendido_at: datetime | None = None
    handover_motivo: str | None = None
    session_state: dict[str, Any] | None = None
    canal: str = WHATSAPP
    external_id: str | None = None
    handle: str | None = None
    tipo_cliente: str = "b2c"

    @property
    def label(self) -> str:
        return resolve_label(self.push_name, self.handle, self.external_id or self.phone)


@dataclass
class WaitingContact:
    id: int
    phone: str | None
    push_name: str | None
    handover_at: datetime
    handover_motivo: str | None
    minutes_waiting: int
    prioridade: int = 0
    assumido_por: str | None = None
    canal: str = WHATSAPP
    external_id: str | None = None
    handle: str | None = None
    last_inbound_at: datetime | None = None
    # Aditive fields (handover-summary-for-agent): `contatos.status` and
    # `contatos.session_state`, needed to build the handover summary
    # (`whatbot/queue.py::build_contact_summary`). `None` for callers that
    # reconstruct a `WaitingContact` without this data (e.g.
    # `contact_resolver.py`'s admin-session replay) — the summary degrades
    # gracefully in that case.
    status: str | None = None
    session_state: dict[str, Any] | None = None

    @property
    def label(self) -> str:
        return resolve_label(self.push_name, self.handle, self.external_id or self.phone)


@dataclass
class MessageRecord:
    id: int
    contact_id: int
    direction: str
    text: str
    created_at: datetime


@dataclass
class ChannelCredential:
    """Row of `canal_credenciais` (see `ensure_schema()`).

    Read/written by `whatbot/ingress.py` (idempotency does not touch this
    table) and by the credential-renewal job
    (`windmill/f/whatbot/refresh_ig_token.py`, `scripts/ig_refresh_token.py`).
    """

    canal: str
    account_id: str | None
    access_token: str
    expires_at: datetime | None
    refreshed_at: datetime | None


@dataclass
class CampaignMessage:
    """Row of `disparo_mensagens` (see `ensure_schema()`, campaign-csv-broadcast).

    One row per contact per imported batch (`lote`), enqueued by
    `whatbot.main.import_campaign` and drained by
    `whatbot.main.send_campaign_queue`.
    """

    id: int
    lote: str
    canal: str
    external_id: str
    mensagem: str
    status: str
    tentativas: int
    erro: str | None
    criado_em: datetime
    enviado_em: datetime | None


class Database:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: Optional[ConnectionPool] = None
        self._logger = logging.getLogger("whatbot.db")

    def init_pool(self) -> None:
        if self._pool is None:
            try:
                self._pool = ConnectionPool(conninfo=self._dsn, min_size=1, max_size=5)
            except Exception as e:
                self._logger.exception("Erro inicializando pool: %s", e)
                raise

    def close(self) -> None:
        if self._pool:
            self._pool.close()

    def ensure_schema(self) -> None:
        self.init_pool()
        sql = """
        -- Usada por `search_contacts_for_admin` para dobrar acentos também no
        -- lado do `push_name`/`handle` armazenados, simetricamente ao fold
        -- (unicodedata NFKD) já aplicado ao termo de busca digitado pelo
        -- admin — sem isso "Joao" não batia contra um contato salvo como
        -- "João" (bug pré-existente, achado durante contact-segmentation-b2b-b2c).
        CREATE EXTENSION IF NOT EXISTS unaccent;
        CREATE TABLE IF NOT EXISTS contatos (
            id SERIAL PRIMARY KEY,
            phone VARCHAR(32) UNIQUE NOT NULL,
            status VARCHAR(32) NOT NULL,
            ia_ativa BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS mensagens (
            id SERIAL PRIMARY KEY,
            contact_id INTEGER REFERENCES contatos(id) ON DELETE CASCADE,
            direction VARCHAR(8) NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS notificacao_admin (
            id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            pendentes_desde_ultimo_lote INTEGER NOT NULL DEFAULT 0,
            ultimo_lote_em TIMESTAMP WITH TIME ZONE
        );
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS push_name VARCHAR(128);
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS handover_at TIMESTAMP WITH TIME ZONE;
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS atendido_at TIMESTAMP WITH TIME ZONE;
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS handover_motivo VARCHAR(64);
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS long_wait_notified BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS prioridade INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS assumido_por VARCHAR(32);
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS bot_resume_at TIMESTAMP WITH TIME ZONE;
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS session_state JSONB NOT NULL DEFAULT '{}'::jsonb;
        -- Multichannel identity (ver openspec/changes/identity-multichannel):
        -- migração aditiva e idempotente, backfill para whatsapp, phone vira
        -- opcional (NULL fora do WhatsApp), chave de identidade passa a ser
        -- (canal, external_id).
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS canal VARCHAR(32);
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS external_id VARCHAR(64);
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS handle VARCHAR(128);
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS last_inbound_at TIMESTAMP WITH TIME ZONE;
        -- contact-segmentation-b2b-b2c: pessoa física (`b2c`) vs. empresa
        -- (`b2b`), validado em Python (`CONTACT_TIPO_CLIENTES`), sem CHECK de
        -- banco — mesmo padrão de `status` (ver design.md, Decisão 1).
        ALTER TABLE contatos ADD COLUMN IF NOT EXISTS tipo_cliente VARCHAR(8) NOT NULL DEFAULT 'b2c';
        UPDATE contatos SET canal = 'whatsapp' WHERE canal IS NULL;
        UPDATE contatos SET external_id = phone WHERE external_id IS NULL;
        ALTER TABLE contatos ALTER COLUMN canal SET NOT NULL;
        ALTER TABLE contatos ALTER COLUMN external_id SET NOT NULL;
        ALTER TABLE contatos ALTER COLUMN phone DROP NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS contatos_canal_external_id_idx
            ON contatos (canal, external_id);
        CREATE TABLE IF NOT EXISTS admin_sessao (
            admin_phone VARCHAR(32) PRIMARY KEY,
            acao VARCHAR(32) NOT NULL,
            candidatos JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS handover_historico (
            id SERIAL PRIMARY KEY,
            contact_id INTEGER REFERENCES contatos(id) ON DELETE SET NULL,
            phone VARCHAR(32) NOT NULL,
            push_name VARCHAR(128),
            handover_at TIMESTAMP WITH TIME ZONE NOT NULL,
            atendido_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            wait_minutes INTEGER NOT NULL DEFAULT 0,
            prioridade INTEGER NOT NULL DEFAULT 0,
            assumido_por VARCHAR(32),
            motivo VARCHAR(64)
        );
        ALTER TABLE handover_historico ADD COLUMN IF NOT EXISTS canal VARCHAR(32);
        ALTER TABLE handover_historico ADD COLUMN IF NOT EXISTS external_id VARCHAR(64);
        UPDATE handover_historico SET canal = 'whatsapp' WHERE canal IS NULL;
        UPDATE handover_historico SET external_id = phone WHERE external_id IS NULL;
        ALTER TABLE handover_historico ALTER COLUMN phone DROP NOT NULL;
        CREATE TABLE IF NOT EXISTS resumo_diario_enviado (
            dia DATE PRIMARY KEY,
            enviado_em TIMESTAMP WITH TIME ZONE DEFAULT now()
        );
        -- Usadas a partir do change instagram-ingestion-service (ver
        -- openspec/changes/identity-multichannel/design.md, Decisão 7): a
        -- criação vive aqui porque este é o único change que altera
        -- ensure_schema() nesta sequência.
        CREATE TABLE IF NOT EXISTS canal_credenciais (
            canal VARCHAR(16) PRIMARY KEY,
            account_id VARCHAR(64),
            access_token TEXT NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE,
            refreshed_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS webhook_eventos (
            canal VARCHAR(16) NOT NULL,
            message_id VARCHAR(128) NOT NULL,
            received_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            PRIMARY KEY (canal, message_id)
        );
        CREATE INDEX IF NOT EXISTS webhook_eventos_received_idx
            ON webhook_eventos (received_at);
        -- Streak de falhas de envio consecutivas por canal, persistido (não
        -- em memória de processo): no Windmill cada execução é um processo
        -- novo, então um contador em memória nunca sobreviveria entre
        -- entregas (ver critic BLOQUEADOR 1, `whatbot/instagram_health.py`).
        CREATE TABLE IF NOT EXISTS canal_envio_falhas (
            canal VARCHAR(16) PRIMARY KEY,
            streak INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        );
        -- Local cache of the WhatsApp Business catalog (catalog-product-sync,
        -- see design.md Decisão 1/2): kept in sync by the
        -- `windmill/f/whatbot/sync_catalog.py` job, resolved with
        -- `Database.resolve_catalog_items` so `productId`/`retailerId` never
        -- needs a synchronous call to the Evolution API during customer
        -- traffic.
        CREATE TABLE IF NOT EXISTS produtos_catalogo (
            product_id VARCHAR(64) PRIMARY KEY,
            nome TEXT,
            preco NUMERIC,
            disponivel BOOLEAN,
            last_synced_at TIMESTAMPTZ
        );
        -- Disparo de mensagens em massa via CSV, com fila e limite de taxa
        -- (campaign-csv-broadcast, ver design.md Decisão 1): fila persistida
        -- no Postgres em vez de memória/fila externa, já que cada execução do
        -- bot roda como um job Windmill novo (processo efêmero). Importação
        -- síncrona (`import_campaign`) enfileira aqui; o worker agendado
        -- (`send_campaign_queue`) drena respeitando `CAMPAIGN_BATCH_SIZE` e
        -- `CAMPAIGN_SEND_INTERVAL_SECONDS` (design.md, Decisão 2).
        CREATE TABLE IF NOT EXISTS disparo_mensagens (
            id SERIAL PRIMARY KEY,
            lote VARCHAR(128) NOT NULL,
            canal VARCHAR(32) NOT NULL DEFAULT 'whatsapp',
            external_id VARCHAR(64) NOT NULL,
            mensagem TEXT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pendente',
            tentativas INTEGER NOT NULL DEFAULT 0,
            erro TEXT,
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT now(),
            enviado_em TIMESTAMP WITH TIME ZONE
        );
        CREATE INDEX IF NOT EXISTS disparo_mensagens_lote_status_idx
            ON disparo_mensagens (lote, status);
        INSERT INTO notificacao_admin (id, pendentes_desde_ultimo_lote) VALUES (1, 0)
        ON CONFLICT (id) DO NOTHING;
        """
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
        except Exception as e:
            self._logger.exception("Erro criando schema: %s", e)
            raise

    @staticmethod
    def _parse_session_state(session_raw: Any) -> dict[str, Any]:
        """Normalize a `session_state` JSONB column value (already a `dict`
        via psycopg's JSONB adapter, a raw JSON string, or `None`/falsy) into
        a plain `dict`. Shared by `_row_to_contact` and `_row_to_waiting`."""
        if isinstance(session_raw, dict):
            return session_raw
        if session_raw:
            try:
                return json.loads(session_raw)
            except (TypeError, json.JSONDecodeError):
                return {}
        return {}

    def _row_to_contact(self, row) -> Contact:
        session_state = self._parse_session_state(row[9] if len(row) > 9 else None)
        return Contact(
            id=row[0],
            phone=row[1],
            status=row[2],
            ia_ativa=row[3],
            created_at=row[4],
            push_name=row[5] if len(row) > 5 else None,
            handover_at=row[6] if len(row) > 6 else None,
            atendido_at=row[7] if len(row) > 7 else None,
            handover_motivo=row[8] if len(row) > 8 else None,
            session_state=session_state,
            canal=row[10] if len(row) > 10 and row[10] else WHATSAPP,
            external_id=row[11] if len(row) > 11 else None,
            handle=row[12] if len(row) > 12 else None,
            tipo_cliente=row[13] if len(row) > 13 and row[13] else "b2c",
        )

    _CONTACT_SELECT = """
        SELECT id, phone, status, ia_ativa, created_at,
               push_name, handover_at, atendido_at, handover_motivo, session_state,
               canal, external_id, handle, tipo_cliente
        FROM contatos
    """

    def get_contact_by_phone(self, phone: str, canal: str | None = None) -> Optional[Contact]:
        """Look up a contact by its channel-scoped identity.

        `phone` is the external identity (phone on WhatsApp, IGSID on
        Instagram, ...); kept named `phone` for compatibility with existing
        WhatsApp call sites, which never pass `canal` explicitly.
        """
        canal = normalize_channel(canal)
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"{self._CONTACT_SELECT} WHERE canal = %s AND external_id = %s",
                        (canal, phone),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                    return self._row_to_contact(row)
        except Exception as e:
            self._logger.exception("Erro buscando contato: %s", e)
            raise

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
        """Create a contact identified by `(canal, external_id)`.

        `phone=` remains a valid kwarg for WhatsApp call sites (compat): when
        `canal` is `whatsapp` (the default), `phone` doubles as `external_id`
        if `external_id` is not given explicitly. For any other channel,
        `phone` is stored as `NULL` (see design.md, Decisão 3) — pass
        `external_id=` instead.
        """
        canal = normalize_channel(canal)
        external_id = external_id or phone
        if not external_id:
            raise ValueError("create_contact requer external_id (ou phone para whatsapp)")
        stored_phone = external_id if canal == WHATSAPP else None
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO contatos
                            (phone, status, ia_ativa, push_name, canal, external_id, handle)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, created_at
                        """,
                        (stored_phone, status, ia_ativa, push_name, canal, external_id, handle),
                    )
                    row = cur.fetchone()
                    return Contact(
                        id=row[0],
                        phone=stored_phone,
                        status=status,
                        ia_ativa=ia_ativa,
                        created_at=row[1],
                        push_name=push_name,
                        canal=canal,
                        external_id=external_id,
                        handle=handle,
                    )
        except Exception as e:
            self._logger.exception("Erro criando contato: %s", e)
            raise

    def update_contact_push_name(self, contact_id: int, push_name: str | None) -> None:
        if not push_name:
            return
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE contatos SET push_name = %s WHERE id = %s",
                    (push_name, contact_id),
                )

    def update_contact_session_state(
        self, contact_id: int, session_state: dict[str, Any]
    ) -> None:
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE contatos SET session_state = %s::jsonb WHERE id = %s",
                        (json.dumps(session_state), contact_id),
                    )
        except Exception as e:
            self._logger.exception("Erro atualizando session_state: %s", e)
            raise

    def update_contact_ia_active(self, contact_id: int, ia_ativa: bool) -> None:
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE contatos SET ia_ativa = %s WHERE id = %s",
                        (ia_ativa, contact_id),
                    )
        except Exception as e:
            self._logger.exception("Erro atualizando ia_ativa: %s", e)
            raise

    def set_contact_status(self, contact_id: int, status: str) -> None:
        """Update `contatos.status` (contact-interest-memory).

        Validated against `CONTACT_STATUSES` in Python before touching the
        DB — raises `ValueError` for anything outside the closed set, the
        same style as other setters in this module (no DB `CHECK`
        constraint).
        """
        if status not in CONTACT_STATUSES:
            raise ValueError(
                f"status inválido: {status!r} (esperado um de {sorted(CONTACT_STATUSES)})"
            )
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE contatos SET status = %s WHERE id = %s",
                        (status, contact_id),
                    )
        except Exception as e:
            self._logger.exception("Erro atualizando status: %s", e)
            raise

    def set_contact_tipo_cliente(self, contact_id: int, tipo_cliente: str) -> None:
        """Update `contatos.tipo_cliente` (contact-segmentation-b2b-b2c).

        Validated against `CONTACT_TIPO_CLIENTES` in Python before touching
        the DB — raises `ValueError` for anything outside the closed set,
        the same style as `set_contact_status`.
        """
        if tipo_cliente not in CONTACT_TIPO_CLIENTES:
            raise ValueError(
                f"tipo_cliente inválido: {tipo_cliente!r} "
                f"(esperado um de {sorted(CONTACT_TIPO_CLIENTES)})"
            )
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE contatos SET tipo_cliente = %s WHERE id = %s",
                        (tipo_cliente, contact_id),
                    )
        except Exception as e:
            self._logger.exception("Erro atualizando tipo_cliente: %s", e)
            raise

    def update_contact_last_inbound(
        self, contact_id: int, when: datetime | None = None
    ) -> None:
        """Record `when` (default: now) as the contact's last inbound message.

        Feeds the Instagram messaging-window check (see
        `whatbot/channels/instagram.py`) — called for every inbound customer
        message, on every channel, from `whatbot/main.py`.
        """
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    if when is None:
                        cur.execute(
                            "UPDATE contatos SET last_inbound_at = now() WHERE id = %s",
                            (contact_id,),
                        )
                    else:
                        cur.execute(
                            "UPDATE contatos SET last_inbound_at = %s WHERE id = %s",
                            (when, contact_id),
                        )
        except Exception as e:
            self._logger.exception("Erro atualizando last_inbound_at: %s", e)
            raise

    def get_last_inbound_at(self, external_id: str, *, canal: str) -> datetime | None:
        """Look up a contact's `last_inbound_at` by its channel-scoped identity.

        Small read accessor meant to be injected into channel clients (e.g.
        `InstagramClient(last_inbound_lookup=...)`), which must not depend on
        `whatbot/db.py` directly (see `openspec/project.md`, "Camadas").

        `canal` is required and keyword-only, deliberately: this signature
        happens to match `Callable[[str], datetime | None]` if called with a
        single positional argument, so a naive `last_inbound_lookup=_db.get_last_inbound_at`
        injection would silently fall back to whatever `normalize_channel(None)`
        resolves to (WhatsApp) instead of the caller's actual channel — see
        critic Importante 5 on `instagram-messaging-window`. Prefer
        `whatbot/channels/instagram.py::instagram_last_inbound_lookup(db)` when
        wiring an `InstagramClient`.
        """
        canal = normalize_channel(canal)
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT last_inbound_at FROM contatos WHERE canal = %s AND external_id = %s",
                        (canal, external_id),
                    )
                    row = cur.fetchone()
                    return row[0] if row else None
        except Exception as e:
            self._logger.exception("Erro buscando last_inbound_at: %s", e)
            raise

    def enroll_handover(
        self,
        contact_id: int,
        motivo: str,
        push_name: str | None = None,
        prioridade: int = 0,
    ) -> None:
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE contatos
                    SET ia_ativa = FALSE,
                        handover_at = now(),
                        atendido_at = NULL,
                        handover_motivo = %s,
                        long_wait_notified = FALSE,
                        prioridade = %s,
                        assumido_por = NULL,
                        push_name = COALESCE(%s, push_name)
                    WHERE id = %s
                    """,
                    (motivo, prioridade, push_name, contact_id),
                )

    def is_waiting(self, phone: str, canal: str | None = None) -> bool:
        contact = self.get_contact_by_phone(phone, canal=canal)
        return (
            contact is not None
            and contact.handover_at is not None
            and contact.atendido_at is None
        )

    def _waiting_select(self) -> str:
        return """
            SELECT id, phone, push_name, handover_at, handover_motivo,
                   EXTRACT(EPOCH FROM (now() - handover_at)) / 60 AS minutes_waiting,
                   prioridade, assumido_por, canal, external_id, handle, last_inbound_at,
                   status, session_state
            FROM contatos
            WHERE handover_at IS NOT NULL AND atendido_at IS NULL
        """

    def _row_to_waiting(self, r) -> WaitingContact:
        return WaitingContact(
            id=r[0],
            phone=r[1],
            push_name=r[2],
            handover_at=r[3],
            handover_motivo=r[4],
            minutes_waiting=int(r[5] or 0),
            prioridade=int(r[6] or 0),
            assumido_por=r[7],
            canal=r[8] if len(r) > 8 and r[8] else WHATSAPP,
            external_id=r[9] if len(r) > 9 else None,
            handle=r[10] if len(r) > 10 else None,
            last_inbound_at=r[11] if len(r) > 11 else None,
            # handover-summary-for-agent: appended at the end of `_waiting_select()`
            # so any raw-SQL caller that still expects the original 12-column
            # shape (`AND canal = ... AND external_id = ...` filters appended
            # by `get_contact_waiting`/`get_long_wait_unnotified`) keeps working.
            status=r[12] if len(r) > 12 else None,
            session_state=self._parse_session_state(r[13]) if len(r) > 13 else None,
        )

    def get_waiting_contacts(self) -> List[WaitingContact]:
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    self._waiting_select()
                    + " ORDER BY prioridade DESC, handover_at ASC"
                )
                return [self._row_to_waiting(r) for r in cur.fetchall()]

    def get_contact_waiting(self, phone: str, canal: str | None = None) -> WaitingContact | None:
        canal = normalize_channel(canal)
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    self._waiting_select() + " AND canal = %s AND external_id = %s",
                    (canal, phone),
                )
                row = cur.fetchone()
                return self._row_to_waiting(row) if row else None

    def get_long_waiting_contacts(self, min_minutes: int) -> List[WaitingContact]:
        waiting = self.get_waiting_contacts()
        return [c for c in waiting if c.minutes_waiting >= min_minutes]

    def mark_long_wait_notified(self, contact_ids: List[int]) -> None:
        if not contact_ids:
            return
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE contatos SET long_wait_notified = TRUE
                    WHERE id = ANY(%s)
                    """,
                    (contact_ids,),
                )

    def increment_handover_batch(self) -> int:
        """Increment batch counter; return new value."""
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE notificacao_admin
                    SET pendentes_desde_ultimo_lote = pendentes_desde_ultimo_lote + 1
                    WHERE id = 1
                    RETURNING pendentes_desde_ultimo_lote
                    """
                )
                row = cur.fetchone()
                return int(row[0])

    def reset_handover_batch(self) -> None:
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE notificacao_admin
                    SET pendentes_desde_ultimo_lote = 0, ultimo_lote_em = now()
                    WHERE id = 1
                    """
                )

    def _archive_handover(
        self,
        cur,
        contact_id: int,
        assumido_por: str | None,
    ) -> None:
        cur.execute(
            """
            SELECT phone, push_name, handover_at, handover_motivo, prioridade,
                   canal, external_id
            FROM contatos WHERE id = %s
            """,
            (contact_id,),
        )
        row = cur.fetchone()
        if not row or row[2] is None:
            return
        phone, push_name, handover_at, motivo, prioridade, canal, external_id = (
            row[0],
            row[1],
            row[2],
            row[3],
            row[4] or 0,
            row[5],
            row[6],
        )
        cur.execute(
            """
            INSERT INTO handover_historico
                (contact_id, phone, push_name, handover_at, atendido_at,
                 wait_minutes, prioridade, assumido_por, motivo, canal, external_id)
            VALUES (
                %s, %s, %s, %s, now(),
                GREATEST(0, EXTRACT(EPOCH FROM (now() - %s)) / 60)::int,
                %s, %s, %s, %s, %s
            )
            """,
            (
                contact_id,
                phone,
                push_name,
                handover_at,
                handover_at,
                prioridade,
                assumido_por,
                motivo,
                canal,
                external_id,
            ),
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
        canal = normalize_channel(canal)
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM contatos
                    WHERE canal = %s AND external_id = %s
                      AND handover_at IS NOT NULL
                      AND atendido_at IS NULL
                    """,
                    (canal, phone),
                )
                row = cur.fetchone()
                if not row:
                    return False
                contact_id = row[0]
                self._archive_handover(cur, contact_id, assumido_por)

                if reativar_bot:
                    resume_sql = "NULL"
                    ia_ativa = True
                elif schedule_resume_hours is not None:
                    resume_sql = f"now() + ({int(schedule_resume_hours)} || ' hours')::interval"
                    ia_ativa = False
                else:
                    resume_sql = "NULL"
                    ia_ativa = False

                cur.execute(
                    f"""
                    UPDATE contatos
                    SET atendido_at = now(),
                        ia_ativa = %s,
                        handover_at = NULL,
                        handover_motivo = NULL,
                        long_wait_notified = FALSE,
                        prioridade = 0,
                        assumido_por = NULL,
                        bot_resume_at = {resume_sql}
                    WHERE id = %s
                    """,
                    (ia_ativa, contact_id),
                )
                return True

    def assumir_contato(
        self, phone: str, admin_phone: str, *, canal: str | None = None
    ) -> WaitingContact | None:
        canal = normalize_channel(canal)
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE contatos
                    SET assumido_por = %s
                    WHERE canal = %s AND external_id = %s
                      AND handover_at IS NOT NULL
                      AND atendido_at IS NULL
                    RETURNING id
                    """,
                    (admin_phone, canal, phone),
                )
                if not cur.fetchone():
                    return None
        return self.get_contact_waiting(phone, canal=canal)

    def reativar_bot(self, phone: str, *, canal: str | None = None) -> bool:
        canal = normalize_channel(canal)
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE contatos
                    SET ia_ativa = TRUE,
                        atendido_at = COALESCE(atendido_at, now()),
                        handover_at = NULL,
                        handover_motivo = NULL,
                        long_wait_notified = FALSE,
                        prioridade = 0,
                        assumido_por = NULL,
                        bot_resume_at = NULL
                    WHERE canal = %s AND external_id = %s
                    RETURNING id
                    """,
                    (canal, phone),
                )
                return cur.fetchone() is not None

    def pausar_bot(self, phone: str, *, canal: str | None = None) -> bool:
        """Manually pause the bot for a contact outside the handover queue
        (`admin-bot-pause`). Mirrors `reativar_bot`'s `(canal, external_id)`
        resolution, but only flips `ia_ativa` — `bot_resume_at` is left
        untouched (design.md, Decisão 2): a manual pause is indefinite, not
        a handover with an automatic resume deadline, so
        `process_auto_reactivations()`'s `bot_resume_at <= now()` sweep must
        never pick these rows up on its own."""
        canal = normalize_channel(canal)
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE contatos
                    SET ia_ativa = FALSE
                    WHERE canal = %s AND external_id = %s
                    RETURNING id
                    """,
                    (canal, phone),
                )
                return cur.fetchone() is not None

    def mark_all_attended(
        self,
        reativar_bot: bool = False,
        assumido_por: str | None = None,
        schedule_resume_hours: int | None = None,
    ) -> int:
        waiting = self.get_waiting_contacts()
        count = 0
        for contact in waiting:
            if self.mark_attended(
                contact.external_id,
                reativar_bot=reativar_bot,
                assumido_por=assumido_por,
                schedule_resume_hours=schedule_resume_hours,
                canal=contact.canal,
            ):
                count += 1
        return count

    def get_daily_handover_stats(self, day) -> dict:
        """Stats for a calendar day (date object)."""
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        COALESCE(AVG(wait_minutes), 0) AS avg_wait,
                        COUNT(*) FILTER (WHERE prioridade >= 1) AS alta_prioridade
                    FROM handover_historico
                    WHERE atendido_at::date = %s
                    """,
                    (day,),
                )
                row = cur.fetchone()
                cur.execute(
                    """
                    SELECT COUNT(*) FROM contatos
                    WHERE handover_at IS NOT NULL AND atendido_at IS NULL
                    """
                )
                still_waiting = int(cur.fetchone()[0])
        return {
            "atendidos": int(row[0] or 0),
            "avg_wait_minutes": int(row[1] or 0),
            "alta_prioridade": int(row[2] or 0),
            "still_waiting": still_waiting,
        }

    def count_handovers_today(self, day) -> int:
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT id FROM handover_historico WHERE handover_at::date = %s
                        UNION ALL
                        SELECT id FROM contatos
                        WHERE handover_at IS NOT NULL AND handover_at::date = %s
                    ) t
                    """,
                    (day, day),
                )
                return int(cur.fetchone()[0] or 0)

    def was_daily_summary_sent(self, day) -> bool:
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM resumo_diario_enviado WHERE dia = %s",
                    (day,),
                )
                return cur.fetchone() is not None

    def mark_daily_summary_sent(self, day) -> None:
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO resumo_diario_enviado (dia) VALUES (%s)
                    ON CONFLICT (dia) DO NOTHING
                    """,
                    (day,),
                )

    def get_long_wait_unnotified(self, min_minutes: int) -> List[WaitingContact]:
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    self._waiting_select()
                    + """
                      AND long_wait_notified = FALSE
                      AND handover_at <= now() - (%s || ' minutes')::interval
                    ORDER BY prioridade DESC, handover_at ASC
                    """,
                    (str(min_minutes),),
                )
                return [self._row_to_waiting(r) for r in cur.fetchall()]

    def save_message(self, contact_id: int, direction: str, text: str) -> None:
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO mensagens (contact_id, direction, text) VALUES (%s, %s, %s)",
                        (contact_id, direction, text),
                    )
        except Exception as e:
            self._logger.exception("Erro salvando mensagem: %s", e)
            raise

    def get_recent_messages(
        self, contact_id: int, limit: int = 10
    ) -> List[MessageRecord]:
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, contact_id, direction, text, created_at FROM mensagens WHERE contact_id = %s ORDER BY created_at DESC LIMIT %s",
                        (contact_id, limit),
                    )
                    rows = cur.fetchall()
                    return [
                        MessageRecord(
                            id=r[0],
                            contact_id=r[1],
                            direction=r[2],
                            text=r[3],
                            created_at=r[4],
                        )
                        for r in rows
                    ]
        except Exception as e:
            self._logger.exception("Erro carregando histórico: %s", e)
            raise

    def process_auto_reactivations(self) -> list[str]:
        """Re-enable bot for contacts past scheduled resume time.

        Returns a human-readable label per contact (name -> handle -> external
        id), never a raw `phone`, since it can be `NULL` for non-WhatsApp
        contacts.
        """
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE contatos
                    SET ia_ativa = TRUE, bot_resume_at = NULL
                    WHERE ia_ativa = FALSE
                      AND bot_resume_at IS NOT NULL
                      AND bot_resume_at <= now()
                    RETURNING phone, push_name, handle, external_id
                    """
                )
                return [
                    resolve_label(r[1], r[2], r[3] or r[0]) for r in cur.fetchall()
                ]

    def save_admin_sessao(
        self, admin_phone: str, acao: str, candidatos: list[dict]
    ) -> None:
        import json

        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO admin_sessao (admin_phone, acao, candidatos)
                    VALUES (%s, %s, %s::jsonb)
                    ON CONFLICT (admin_phone) DO UPDATE
                    SET acao = EXCLUDED.acao,
                        candidatos = EXCLUDED.candidatos,
                        created_at = now()
                    """,
                    (admin_phone, acao, json.dumps(candidatos)),
                )

    def get_admin_sessao(self, admin_phone: str) -> tuple[str, list[dict]] | None:
        import json

        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT acao, candidatos FROM admin_sessao
                    WHERE admin_phone = %s
                      AND created_at > now() - interval '10 minutes'
                    """,
                    (admin_phone,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                candidatos = row[1]
                if isinstance(candidatos, str):
                    candidatos = json.loads(candidatos)
                return row[0], candidatos

    def clear_admin_sessao(self, admin_phone: str) -> None:
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM admin_sessao WHERE admin_phone = %s",
                    (admin_phone,),
                )

    def search_contacts_for_admin(self, query: str) -> list[dict]:
        """Search contacts by phone fragment or name (for reactivate).

        Not scoped to a single channel: the secretariat searches by name
        across every contact, WhatsApp or not. `phone` in the result may be
        `None` for non-WhatsApp contacts — callers use `label`/`external_id`.
        """
        import unicodedata

        phone = re.sub(r"\D", "", query)
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                if phone and len(phone) >= 8:
                    # `phone` is only ever set for WhatsApp contacts (NULL
                    # otherwise), so also match `external_id` directly —
                    # non-WhatsApp identities (e.g. an IGSID) never populate
                    # `phone` (see design.md, Decisão 3).
                    cur.execute(
                        """
                        SELECT id, phone, push_name, ia_ativa,
                               handover_at IS NOT NULL AND atendido_at IS NULL AS in_queue,
                               canal, external_id, handle, tipo_cliente
                        FROM contatos
                        WHERE phone LIKE %s OR external_id LIKE %s
                        ORDER BY created_at DESC LIMIT 5
                        """,
                        (f"%{phone[-8:]}%", f"%{phone[-8:]}%"),
                    )
                else:
                    folded = unicodedata.normalize("NFKD", query.lower())
                    term = f"%{folded.encode('ascii', 'ignore').decode('ascii')}%"
                    cur.execute(
                        """
                        SELECT id, phone, push_name, ia_ativa,
                               handover_at IS NOT NULL AND atendido_at IS NULL AS in_queue,
                               canal, external_id, handle, tipo_cliente
                        FROM contatos
                        WHERE unaccent(push_name) ILIKE %s OR unaccent(handle) ILIKE %s
                        ORDER BY created_at DESC LIMIT 5
                        """,
                        (term, term),
                    )
                return [
                    {
                        "id": r[0],
                        "phone": r[1],
                        "push_name": r[2],
                        "ia_ativa": r[3],
                        "in_queue": r[4],
                        "canal": r[5],
                        "external_id": r[6],
                        "handle": r[7],
                        "tipo_cliente": r[8],
                        "label": resolve_label(r[2], r[7], r[6] or r[1]),
                    }
                    for r in cur.fetchall()
                ]

    # -- webhook idempotency (instagram-ingestion-service) ---------------

    def record_webhook_event(self, canal: str, message_id: str) -> bool:
        """Record `(canal, message_id)` in `webhook_eventos`; return whether it is new.

        Single source of truth for Requirement "Idempotência de entrega de
        webhook": the first delivery inserts a new row and returns `True`; any
        reentrega hits the `(canal, message_id)` primary key and returns
        `False` — the caller (`whatbot/main.py::main()`) discards it without
        error, which is what stops the Meta webhook from retrying forever.
        Called from `main()` directly (not only from `whatbot/ingress.py`) so
        the guarantee holds regardless of transport — see
        `tests/test_main_e2e.py`, idempotency at the `main()` seam.
        """
        canal = normalize_channel(canal)
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO webhook_eventos (canal, message_id)
                        VALUES (%s, %s)
                        ON CONFLICT (canal, message_id) DO NOTHING
                        """,
                        (canal, message_id),
                    )
                    return cur.rowcount > 0
        except Exception as e:
            self._logger.exception("Erro registrando evento de webhook: %s", e)
            raise

    def get_last_webhook_event_at(self, canal: str | None = None) -> datetime | None:
        """Most recent `received_at` for `canal`, or `None` if none was ever recorded.

        Feeds the "ausência prolongada de eventos" health alert
        (`whatbot/instagram_health.py`).
        """
        canal = normalize_channel(canal)
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT MAX(received_at) FROM webhook_eventos WHERE canal = %s",
                        (canal,),
                    )
                    row = cur.fetchone()
                    return row[0] if row else None
        except Exception as e:
            self._logger.exception("Erro buscando último evento de webhook: %s", e)
            raise

    def purge_old_webhook_events(self, older_than_days: int = 7) -> int:
        """Delete `webhook_eventos` rows older than `older_than_days`; return count removed.

        Called from the existing scheduled job (`run_periodic_queue_checks`),
        per tasks.md 2.2 — no new Windmill job needed just for this.
        """
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM webhook_eventos WHERE received_at < now() - (%s || ' days')::interval",
                        (str(max(0, older_than_days)),),
                    )
                    return cur.rowcount
        except Exception as e:
            self._logger.exception("Erro limpando webhook_eventos: %s", e)
            raise

    def delete_webhook_event(self, canal: str, message_id: str) -> None:
        """Undo `record_webhook_event` for `(canal, message_id)`.

        Called from `whatbot/main.py::main()` when processing fails *after*
        idempotency was already recorded, so the next Meta reentrega is not
        discarded as a duplicate and the customer is not permanently left
        without an answer (critic BLOQUEADOR 2).
        """
        canal = normalize_channel(canal)
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM webhook_eventos WHERE canal = %s AND message_id = %s",
                        (canal, message_id),
                    )
        except Exception as e:
            self._logger.exception("Erro desfazendo idempotência de evento: %s", e)
            raise

    # -- send-failure streak (instagram-ingestion-service) ---------------

    def increment_send_fail_streak(self, canal: str) -> int:
        """Increment `canal`'s consecutive-send-failure streak; return the new value.

        Persisted (see `ensure_schema` `canal_envio_falhas`) so the streak
        survives across Windmill executions, which each run in a fresh
        process (critic BLOQUEADOR 1).
        """
        canal = normalize_channel(canal)
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO canal_envio_falhas (canal, streak, updated_at)
                        VALUES (%s, 1, now())
                        ON CONFLICT (canal) DO UPDATE
                        SET streak = canal_envio_falhas.streak + 1, updated_at = now()
                        RETURNING streak
                        """,
                        (canal,),
                    )
                    row = cur.fetchone()
                    return row[0] if row else 1
        except Exception as e:
            self._logger.exception("Erro incrementando streak de falhas de envio: %s", e)
            raise

    def reset_send_fail_streak(self, canal: str) -> None:
        """Zero `canal`'s consecutive-send-failure streak (a success resets it)."""
        canal = normalize_channel(canal)
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO canal_envio_falhas (canal, streak, updated_at)
                        VALUES (%s, 0, now())
                        ON CONFLICT (canal) DO UPDATE
                        SET streak = 0, updated_at = now()
                        """,
                        (canal,),
                    )
        except Exception as e:
            self._logger.exception("Erro resetando streak de falhas de envio: %s", e)
            raise

    # -- channel credentials (instagram-ingestion-service) ---------------

    def upsert_channel_credential(
        self,
        canal: str,
        access_token: str,
        *,
        account_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        """Insert or replace the credential for `canal` (one row per channel)."""
        canal = normalize_channel(canal)
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO canal_credenciais
                            (canal, account_id, access_token, expires_at, refreshed_at)
                        VALUES (%s, %s, %s, %s, now())
                        ON CONFLICT (canal) DO UPDATE
                        SET account_id = EXCLUDED.account_id,
                            access_token = EXCLUDED.access_token,
                            expires_at = EXCLUDED.expires_at,
                            refreshed_at = now()
                        """,
                        (canal, account_id, access_token, expires_at),
                    )
        except Exception as e:
            self._logger.exception("Erro salvando credencial de canal: %s", e)
            raise

    def get_channel_credential(self, canal: str) -> ChannelCredential | None:
        canal = normalize_channel(canal)
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT canal, account_id, access_token, expires_at, refreshed_at
                        FROM canal_credenciais WHERE canal = %s
                        """,
                        (canal,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                    return ChannelCredential(
                        canal=row[0],
                        account_id=row[1],
                        access_token=row[2],
                        expires_at=row[3],
                        refreshed_at=row[4],
                    )
        except Exception as e:
            self._logger.exception("Erro buscando credencial de canal: %s", e)
            raise

    # -- product catalog cache (catalog-product-sync) ----------------------

    def upsert_catalog_products(self, products: list[dict]) -> None:
        """Upsert `produtos_catalogo` by `product_id`.

        Called from `whatbot.main.sync_catalog()` right after
        `EvolutionApiClient.fetch_catalog()`. Each `product` dict is expected
        to already carry `product_id`, `nome`, `preco`, `disponivel` (the
        shape `fetch_catalog()` returns) — `last_synced_at` is always bumped
        to `now()` on every run that sees the product, whether or not its
        other fields changed, so it reflects the most recent successful sync
        (see design.md, Decisão 2).
        """
        if not products:
            return
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    for product in products:
                        cur.execute(
                            """
                            INSERT INTO produtos_catalogo
                                (product_id, nome, preco, disponivel, last_synced_at)
                            VALUES (%s, %s, %s, %s, now())
                            ON CONFLICT (product_id) DO UPDATE
                            SET nome = EXCLUDED.nome,
                                preco = EXCLUDED.preco,
                                disponivel = EXCLUDED.disponivel,
                                last_synced_at = now()
                            """,
                            (
                                product["product_id"],
                                product.get("nome"),
                                product.get("preco"),
                                product.get("disponivel"),
                            ),
                        )
        except Exception as e:
            self._logger.exception("Erro sincronizando catálogo de produtos: %s", e)
            raise

    def resolve_catalog_items(self, product_ids: list[str]) -> list[dict]:
        """Resolve `productId`/`retailerId` values to name/price/availability.

        Used by `catalog-order-capture` (enriching a captured order) and by
        `handover-summary-for-agent` (building the handover summary). An id
        absent from the local cache is simply omitted from the result — never
        raises (see spec "Item desconhecido não quebra a resolução dos
        demais").
        """
        if not product_ids:
            return []
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT product_id, nome, preco, disponivel
                        FROM produtos_catalogo
                        WHERE product_id = ANY(%s)
                        """,
                        (list(product_ids),),
                    )
                    return [
                        {
                            "product_id": r[0],
                            "nome": r[1],
                            "preco": r[2],
                            "disponivel": r[3],
                        }
                        for r in cur.fetchall()
                    ]
        except Exception as e:
            self._logger.exception("Erro resolvendo itens do catálogo: %s", e)
            raise

    # -- mass-broadcast campaign queue (campaign-csv-broadcast) -----------

    _CAMPAIGN_MESSAGE_SELECT = """
        SELECT id, lote, canal, external_id, mensagem, status,
               tentativas, erro, criado_em, enviado_em
        FROM disparo_mensagens
    """

    def _row_to_campaign_message(self, row) -> CampaignMessage:
        return CampaignMessage(
            id=row[0],
            lote=row[1],
            canal=row[2],
            external_id=row[3],
            mensagem=row[4],
            status=row[5],
            tentativas=row[6],
            erro=row[7],
            criado_em=row[8],
            enviado_em=row[9],
        )

    def insert_campaign_message(
        self, lote: str, canal: str, external_id: str, mensagem: str
    ) -> int:
        """Enqueue a single `pendente` row for `lote`. Called once per valid
        CSV line by `whatbot.main.import_campaign`."""
        canal = normalize_channel(canal)
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO disparo_mensagens (lote, canal, external_id, mensagem)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id
                        """,
                        (lote, canal, external_id, mensagem),
                    )
                    return cur.fetchone()[0]
        except Exception as e:
            self._logger.exception("Erro inserindo mensagem de disparo: %s", e)
            raise

    def get_pending_campaign_messages(self, limit: int) -> list[CampaignMessage]:
        """Up to `limit` `pendente` rows, oldest first — the batch a single
        `send_campaign_queue` run processes (design.md, Decisão 2)."""
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        self._CAMPAIGN_MESSAGE_SELECT
                        + " WHERE status = 'pendente' ORDER BY criado_em ASC LIMIT %s",
                        (limit,),
                    )
                    return [self._row_to_campaign_message(r) for r in cur.fetchall()]
        except Exception as e:
            self._logger.exception("Erro buscando mensagens pendentes de disparo: %s", e)
            raise

    def mark_campaign_message_sent(self, message_id: int) -> None:
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE disparo_mensagens
                        SET status = 'enviado', enviado_em = now()
                        WHERE id = %s
                        """,
                        (message_id,),
                    )
        except Exception as e:
            self._logger.exception("Erro marcando mensagem de disparo como enviada: %s", e)
            raise

    def mark_campaign_message_retry(
        self, message_id: int, tentativas: int, erro: str
    ) -> None:
        """Record a retryable failure: bump `tentativas`, keep `status =
        'pendente'` for the next `send_campaign_queue` run."""
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE disparo_mensagens
                        SET tentativas = %s, erro = %s
                        WHERE id = %s
                        """,
                        (tentativas, erro, message_id),
                    )
        except Exception as e:
            self._logger.exception("Erro registrando nova tentativa de disparo: %s", e)
            raise

    def mark_campaign_message_failed(self, message_id: int, erro: str) -> None:
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE disparo_mensagens
                        SET status = 'falha', erro = %s
                        WHERE id = %s
                        """,
                        (erro, message_id),
                    )
        except Exception as e:
            self._logger.exception("Erro marcando mensagem de disparo como falha: %s", e)
            raise

    def mark_campaign_message_skipped(self, message_id: int) -> None:
        """Contact has `ia_ativa = FALSE` at send time (design.md, Decisão 4)."""
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE disparo_mensagens SET status = 'pulado' WHERE id = %s",
                        (message_id,),
                    )
        except Exception as e:
            self._logger.exception("Erro marcando mensagem de disparo como pulada: %s", e)
            raise

    def get_campaign_status(self, lote: str) -> dict:
        """Count of rows per `status` for `lote` — feeds the admin
        `campaign_status` command. Always includes every status in
        `CAMPAIGN_MESSAGE_STATUSES`, zero-filled, even if `lote` has none."""
        self.init_pool()
        counts = {status: 0 for status in CAMPAIGN_MESSAGE_STATUSES}
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT status, COUNT(*) FROM disparo_mensagens
                        WHERE lote = %s
                        GROUP BY status
                        """,
                        (lote,),
                    )
                    for status, count in cur.fetchall():
                        counts[status] = int(count)
                    return counts
        except Exception as e:
            self._logger.exception("Erro buscando status do disparo: %s", e)
            raise
