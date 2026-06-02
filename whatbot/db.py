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


@dataclass
class Contact:
    id: int
    phone: str
    status: str
    ia_ativa: bool
    created_at: datetime
    push_name: str | None = None
    handover_at: datetime | None = None
    atendido_at: datetime | None = None
    handover_motivo: str | None = None
    session_state: dict[str, Any] | None = None


@dataclass
class WaitingContact:
    id: int
    phone: str
    push_name: str | None
    handover_at: datetime
    handover_motivo: str | None
    minutes_waiting: int
    prioridade: int = 0
    assumido_por: str | None = None


@dataclass
class MessageRecord:
    id: int
    contact_id: int
    direction: str
    text: str
    created_at: datetime


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
        CREATE TABLE IF NOT EXISTS resumo_diario_enviado (
            dia DATE PRIMARY KEY,
            enviado_em TIMESTAMP WITH TIME ZONE DEFAULT now()
        );
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

    def _row_to_contact(self, row) -> Contact:
        session_raw = row[9] if len(row) > 9 else None
        session_state: dict[str, Any] | None
        if isinstance(session_raw, dict):
            session_state = session_raw
        elif session_raw:
            try:
                session_state = json.loads(session_raw)
            except (TypeError, json.JSONDecodeError):
                session_state = {}
        else:
            session_state = {}
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
        )

    _CONTACT_SELECT = """
        SELECT id, phone, status, ia_ativa, created_at,
               push_name, handover_at, atendido_at, handover_motivo, session_state
        FROM contatos
    """

    def get_contact_by_phone(self, phone: str) -> Optional[Contact]:
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"{self._CONTACT_SELECT} WHERE phone = %s", (phone,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    return self._row_to_contact(row)
        except Exception as e:
            self._logger.exception("Erro buscando contato: %s", e)
            raise

    def create_contact(
        self,
        phone: str,
        status: str = "novo_lead",
        ia_ativa: bool = True,
        push_name: str | None = None,
    ) -> Contact:
        self.init_pool()
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO contatos (phone, status, ia_ativa, push_name)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id, created_at
                        """,
                        (phone, status, ia_ativa, push_name),
                    )
                    row = cur.fetchone()
                    return Contact(
                        id=row[0],
                        phone=phone,
                        status=status,
                        ia_ativa=ia_ativa,
                        created_at=row[1],
                        push_name=push_name,
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

    def is_waiting(self, phone: str) -> bool:
        contact = self.get_contact_by_phone(phone)
        return (
            contact is not None
            and contact.handover_at is not None
            and contact.atendido_at is None
        )

    def _waiting_select(self) -> str:
        return """
            SELECT id, phone, push_name, handover_at, handover_motivo,
                   EXTRACT(EPOCH FROM (now() - handover_at)) / 60 AS minutes_waiting,
                   prioridade, assumido_por
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

    def get_contact_waiting(self, phone: str) -> WaitingContact | None:
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    self._waiting_select() + " AND phone = %s",
                    (phone,),
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
        phone: str,
        assumido_por: str | None,
    ) -> None:
        cur.execute(
            """
            SELECT push_name, handover_at, handover_motivo, prioridade
            FROM contatos WHERE id = %s
            """,
            (contact_id,),
        )
        row = cur.fetchone()
        if not row or row[1] is None:
            return
        push_name, handover_at, motivo, prioridade = row[0], row[1], row[2], row[3] or 0
        cur.execute(
            """
            INSERT INTO handover_historico
                (contact_id, phone, push_name, handover_at, atendido_at,
                 wait_minutes, prioridade, assumido_por, motivo)
            VALUES (
                %s, %s, %s, %s, now(),
                GREATEST(0, EXTRACT(EPOCH FROM (now() - %s)) / 60)::int,
                %s, %s, %s
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
            ),
        )

    def mark_attended(
        self,
        phone: str,
        reativar_bot: bool = False,
        assumido_por: str | None = None,
        schedule_resume_hours: int | None = None,
    ) -> bool:
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM contatos
                    WHERE phone = %s
                      AND handover_at IS NOT NULL
                      AND atendido_at IS NULL
                    """,
                    (phone,),
                )
                row = cur.fetchone()
                if not row:
                    return False
                contact_id = row[0]
                self._archive_handover(cur, contact_id, phone, assumido_por)

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

    def assumir_contato(self, phone: str, admin_phone: str) -> WaitingContact | None:
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE contatos
                    SET assumido_por = %s
                    WHERE phone = %s
                      AND handover_at IS NOT NULL
                      AND atendido_at IS NULL
                    RETURNING id
                    """,
                    (admin_phone, phone),
                )
                if not cur.fetchone():
                    return None
        return self.get_contact_waiting(phone)

    def reativar_bot(self, phone: str) -> bool:
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
                    WHERE phone = %s
                    RETURNING id
                    """,
                    (phone,),
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
                contact.phone,
                reativar_bot=reativar_bot,
                assumido_por=assumido_por,
                schedule_resume_hours=schedule_resume_hours,
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

    def get_last_inbound_message(self, contact_id: int) -> str | None:
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT text FROM mensagens
                    WHERE contact_id = %s AND direction = 'in'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (contact_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None

    def process_auto_reactivations(self) -> list[str]:
        """Re-enable bot for contacts past scheduled resume time."""
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
                    RETURNING phone
                    """
                )
                return [r[0] for r in cur.fetchall()]

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
        """Search contacts by phone fragment or name (for reactivate)."""
        import unicodedata

        phone = re.sub(r"\D", "", query)
        self.init_pool()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                if phone and len(phone) >= 8:
                    cur.execute(
                        """
                        SELECT id, phone, push_name, ia_ativa,
                               handover_at IS NOT NULL AND atendido_at IS NULL AS in_queue
                        FROM contatos WHERE phone LIKE %s
                        ORDER BY created_at DESC LIMIT 5
                        """,
                        (f"%{phone[-8:]}%",),
                    )
                else:
                    folded = unicodedata.normalize("NFKD", query.lower())
                    term = f"%{folded.encode('ascii', 'ignore').decode('ascii')}%"
                    cur.execute(
                        """
                        SELECT id, phone, push_name, ia_ativa,
                               handover_at IS NOT NULL AND atendido_at IS NULL AS in_queue
                        FROM contatos
                        WHERE push_name ILIKE %s
                        ORDER BY created_at DESC LIMIT 5
                        """,
                        (term,),
                    )
                return [
                    {
                        "id": r[0],
                        "phone": r[1],
                        "push_name": r[2],
                        "ia_ativa": r[3],
                        "in_queue": r[4],
                    }
                    for r in cur.fetchall()
                ]
