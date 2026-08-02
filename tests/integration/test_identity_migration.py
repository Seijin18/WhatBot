"""Migration test against a real Postgres — not part of `make test`.

`python -m unittest discover -s tests -p 'test_*.py'` does not recurse into
`tests/integration/` (no `__init__.py`, see openspec/changes/identity-multichannel/
design.md, Decisão 2), so this file is invisible to `make test`. `pytest -q`
*would* collect it, but every test here self-skips via `SkipTest` when
`WHATBOT_TEST_DSN` is not configured, so the observable behaviour of both ways
of running the suite is the same.

Run explicitly against the `db` service from `docker-compose.yml`, e.g.:

    WHATBOT_TEST_DSN=postgresql://whatbot:whatbot@localhost:5432/whatbot \
        python -m pytest tests/integration/test_identity_migration.py -q
"""

from __future__ import annotations

import os
import unittest
import uuid
from datetime import datetime, timezone

try:
    import psycopg
except ImportError:  # pragma: no cover - psycopg is a project dependency
    psycopg = None

from whatbot.db import Database

ENV_TEST_DSN = "WHATBOT_TEST_DSN"


def _dump_table(cur, table: str, order_by: str = "id") -> list[tuple]:
    cur.execute(f"SELECT * FROM {table} ORDER BY {order_by}")
    return cur.fetchall()


@unittest.skipUnless(
    os.getenv(ENV_TEST_DSN) and psycopg is not None,
    f"{ENV_TEST_DSN} não configurado — teste de migração pulado (requer Postgres real)",
)
class TestIdentityMigration(unittest.TestCase):
    """Requirement 'Identidade do contato por canal', cenário 'Migração de
    base existente' (openspec/changes/identity-multichannel/specs/identity/spec.md)."""

    def setUp(self) -> None:
        self.base_dsn = os.environ[ENV_TEST_DSN]
        self.schema = f"whatbot_migration_test_{uuid.uuid4().hex[:8]}"
        self._admin_conn = psycopg.connect(self.base_dsn, autocommit=True)
        with self._admin_conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA {self.schema}")
        self.addCleanup(self._drop_schema)

        # A dedicated DSN scoping every connection (raw and pooled) to the
        # disposable schema, so this test never touches the real `public`
        # tables even if run against a shared database.
        self.scoped_dsn = (
            f"{self.base_dsn}"
            f"{'&' if '?' in self.base_dsn else '?'}"
            f"options=-csearch_path%3D{self.schema}"
        )

    def _drop_schema(self) -> None:
        with self._admin_conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {self.schema} CASCADE")
        self._admin_conn.close()

    def _connect_scoped(self):
        conn = psycopg.connect(self.scoped_dsn, autocommit=True)
        return conn

    def _create_old_format_schema(self, conn) -> None:
        """Pre-migration schema: no `canal`/`external_id`, `phone` NOT NULL."""
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE contatos (
                    id SERIAL PRIMARY KEY,
                    phone VARCHAR(32) UNIQUE NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    ia_ativa BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                );
                CREATE TABLE handover_historico (
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
                """
            )
            cur.execute(
                "INSERT INTO contatos (phone, status, ia_ativa) VALUES (%s, %s, %s) RETURNING id",
                ("5511999999999", "novo_lead", True),
            )
            contact_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO handover_historico
                    (contact_id, phone, push_name, handover_at, wait_minutes, motivo)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    contact_id,
                    "5511999999999",
                    "Maria",
                    datetime.now(timezone.utc),
                    5,
                    "pedido_do_cliente",
                ),
            )

    def test_migration_backfills_canal_and_external_id_without_losing_rows(self):
        conn = self._connect_scoped()
        self.addCleanup(conn.close)
        self._create_old_format_schema(conn)

        db = Database(self.scoped_dsn)
        self.addCleanup(db.close)
        db.ensure_schema()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT phone, canal, external_id FROM contatos ORDER BY id"
            )
            rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        phone, canal, external_id = rows[0]
        self.assertEqual(phone, "5511999999999")
        self.assertEqual(canal, "whatsapp")
        self.assertEqual(external_id, "5511999999999")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT phone, canal, external_id FROM handover_historico ORDER BY id"
            )
            hist_rows = cur.fetchall()
        self.assertEqual(len(hist_rows), 1)
        hist_phone, hist_canal, hist_external_id = hist_rows[0]
        self.assertEqual(hist_phone, "5511999999999")
        self.assertEqual(hist_canal, "whatsapp")
        self.assertEqual(hist_external_id, "5511999999999")

    def test_running_the_migration_twice_is_a_no_op(self):
        conn = self._connect_scoped()
        self.addCleanup(conn.close)
        self._create_old_format_schema(conn)

        db = Database(self.scoped_dsn)
        self.addCleanup(db.close)
        db.ensure_schema()
        with conn.cursor() as cur:
            first_contatos = _dump_table(cur, "contatos")
            first_historico = _dump_table(cur, "handover_historico")

        db.ensure_schema()
        with conn.cursor() as cur:
            second_contatos = _dump_table(cur, "contatos")
            second_historico = _dump_table(cur, "handover_historico")

        self.assertEqual(first_contatos, second_contatos)
        self.assertEqual(first_historico, second_historico)

    def test_duplicate_canal_external_id_is_rejected(self):
        conn = self._connect_scoped()
        self.addCleanup(conn.close)
        self._create_old_format_schema(conn)

        db = Database(self.scoped_dsn)
        self.addCleanup(db.close)
        db.ensure_schema()

        with self.assertRaises(Exception):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO contatos (phone, status, ia_ativa, canal, external_id)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (None, "novo_lead", True, "whatsapp", "5511999999999"),
                )


if __name__ == "__main__":
    unittest.main()
