"""Migration test against a real Postgres — not part of `make test`.

Same shape as `tests/integration/test_identity_migration.py`: not collected
by `python -m unittest discover -s tests -p 'test_*.py'` (no `__init__.py`
under `tests/integration/`), and every test here self-skips via `SkipTest`
when `WHATBOT_TEST_DSN` is not configured, so `pytest -q` behaves the same
way as plain `unittest discover`.

Run explicitly against the `db` service from `docker-compose.yml`, e.g.:

    WHATBOT_TEST_DSN=postgresql://whatbot:whatbot@localhost:5432/whatbot \
        python -m pytest tests/integration/test_tipo_cliente_migration.py -q
"""

from __future__ import annotations

import os
import unittest
import uuid

try:
    import psycopg
except ImportError:  # pragma: no cover - psycopg is a project dependency
    psycopg = None

from whatbot.db import Database

ENV_TEST_DSN = "WHATBOT_TEST_DSN"


@unittest.skipUnless(
    os.getenv(ENV_TEST_DSN) and psycopg is not None,
    f"{ENV_TEST_DSN} não configurado — teste de migração pulado (requer Postgres real)",
)
class TestTipoClienteMigration(unittest.TestCase):
    """Requirement 'Contato tem tipo de cliente', cenário 'Migração de base
    existente' (openspec/changes/contact-segmentation-b2b-b2c/specs/contacts/spec.md)."""

    def setUp(self) -> None:
        self.base_dsn = os.environ[ENV_TEST_DSN]
        self.schema = f"whatbot_tipo_cliente_test_{uuid.uuid4().hex[:8]}"
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
        return psycopg.connect(self.scoped_dsn, autocommit=True)

    def _create_pre_tipo_cliente_schema(self, conn) -> None:
        """Schema shape right before this change: `canal`/`external_id`
        already exist (identity-multichannel), but no `tipo_cliente`
        column yet."""
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE contatos (
                    id SERIAL PRIMARY KEY,
                    phone VARCHAR(32),
                    status VARCHAR(32) NOT NULL,
                    ia_ativa BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    canal VARCHAR(32) NOT NULL DEFAULT 'whatsapp',
                    external_id VARCHAR(64)
                );
                """
            )
            cur.execute(
                """
                INSERT INTO contatos (phone, status, ia_ativa, canal, external_id)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
                """,
                ("5511999999999", "novo_lead", True, "whatsapp", "5511999999999"),
            )

    def test_migration_backfills_tipo_cliente_as_b2c(self):
        conn = self._connect_scoped()
        self.addCleanup(conn.close)
        self._create_pre_tipo_cliente_schema(conn)

        db = Database(self.scoped_dsn)
        self.addCleanup(db.close)
        db.ensure_schema()

        with conn.cursor() as cur:
            cur.execute("SELECT phone, tipo_cliente FROM contatos ORDER BY id")
            rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        phone, tipo_cliente = rows[0]
        self.assertEqual(phone, "5511999999999")
        self.assertEqual(tipo_cliente, "b2c")

    def test_running_the_migration_twice_does_not_alter_existing_contacts(self):
        conn = self._connect_scoped()
        self.addCleanup(conn.close)
        self._create_pre_tipo_cliente_schema(conn)

        db = Database(self.scoped_dsn)
        self.addCleanup(db.close)
        db.ensure_schema()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM contatos ORDER BY id")
            first = cur.fetchall()

        db.ensure_schema()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM contatos ORDER BY id")
            second = cur.fetchall()

        self.assertEqual(first, second)

    def test_new_contact_created_after_migration_defaults_to_b2c(self):
        conn = self._connect_scoped()
        self.addCleanup(conn.close)
        self._create_pre_tipo_cliente_schema(conn)

        db = Database(self.scoped_dsn)
        self.addCleanup(db.close)
        db.ensure_schema()

        contact = db.create_contact(phone="5511888888888", push_name="Nova")
        self.assertEqual(contact.tipo_cliente, "b2c")

        fetched = db.get_contact_by_phone("5511888888888")
        self.assertEqual(fetched.tipo_cliente, "b2c")


if __name__ == "__main__":
    unittest.main()
