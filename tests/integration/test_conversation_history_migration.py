"""Migration test against a real Postgres — not part of `make test`.

Same pattern as `test_identity_migration.py`: self-skips when
`WHATBOT_TEST_DSN` is not configured, runs `Database.ensure_schema()`
against a disposable schema simulating a pre-existing install (old-format
`mensagens`, no `media_arquivos` table) and checks the
conversation-history-media-storage migration is additive, idempotent, and
does not lose rows.

    WHATBOT_TEST_DSN=postgresql://whatbot:whatbot@localhost:5432/whatbot \
        python -m pytest tests/integration/test_conversation_history_migration.py -q
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


def _dump_table(cur, table: str, order_by: str = "id") -> list[tuple]:
    cur.execute(f"SELECT * FROM {table} ORDER BY {order_by}")
    return cur.fetchall()


@unittest.skipUnless(
    os.getenv(ENV_TEST_DSN) and psycopg is not None,
    f"{ENV_TEST_DSN} não configurado — teste de migração pulado (requer Postgres real)",
)
class TestConversationHistoryMigration(unittest.TestCase):
    """Requirements "Payload bruto persistido por mensagem" e "Mídia
    recebida é baixada e referenciada" (`openspec/specs/message-history/`)."""

    def setUp(self) -> None:
        self.base_dsn = os.environ[ENV_TEST_DSN]
        self.schema = f"whatbot_msg_migration_test_{uuid.uuid4().hex[:8]}"
        self._admin_conn = psycopg.connect(self.base_dsn, autocommit=True)
        with self._admin_conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA {self.schema}")
        self.addCleanup(self._drop_schema)

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

    def _create_old_format_schema(self, conn) -> int:
        """Pre-migration schema: `mensagens` sem canal/message_id/payload/
        media_id, sem tabela `media_arquivos`. Devolve o `contact_id` criado."""
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
                CREATE TABLE mensagens (
                    id SERIAL PRIMARY KEY,
                    contact_id INTEGER REFERENCES contatos(id) ON DELETE CASCADE,
                    direction VARCHAR(8) NOT NULL,
                    text TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                );
                """
            )
            cur.execute(
                "INSERT INTO contatos (phone, status, ia_ativa) VALUES (%s, %s, %s) RETURNING id",
                ("5511999999999", "novo_lead", True),
            )
            contact_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO mensagens (contact_id, direction, text) VALUES (%s, %s, %s)",
                (contact_id, "in", "mensagem antiga, pré-migração"),
            )
        return contact_id

    def test_migration_adds_columns_and_media_table_without_losing_rows(self):
        conn = self._connect_scoped()
        self.addCleanup(conn.close)
        contact_id = self._create_old_format_schema(conn)

        db = Database(self.scoped_dsn)
        self.addCleanup(db.close)
        db.ensure_schema()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT contact_id, text, canal, message_id, payload, media_id "
                "FROM mensagens ORDER BY id"
            )
            rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        row_contact_id, text, canal, message_id, payload, media_id = rows[0]
        self.assertEqual(row_contact_id, contact_id)
        self.assertEqual(text, "mensagem antiga, pré-migração")
        # Backfill: `mensagens` pré-existente ganha canal='whatsapp'.
        self.assertEqual(canal, "whatsapp")
        self.assertIsNone(message_id)
        self.assertIsNone(payload)
        self.assertIsNone(media_id)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'media_arquivos'"
            )
            columns = {r[0] for r in cur.fetchall()}
        self.assertIn("storage_key", columns)
        self.assertIn("origem_media_id", columns)

    def test_running_the_migration_twice_is_a_no_op(self):
        conn = self._connect_scoped()
        self.addCleanup(conn.close)
        self._create_old_format_schema(conn)

        db = Database(self.scoped_dsn)
        self.addCleanup(db.close)
        db.ensure_schema()
        with conn.cursor() as cur:
            first_mensagens = _dump_table(cur, "mensagens")

        db.ensure_schema()
        with conn.cursor() as cur:
            second_mensagens = _dump_table(cur, "mensagens")

        self.assertEqual(first_mensagens, second_mensagens)

    def test_new_message_can_carry_canal_message_id_payload_and_media(self):
        conn = self._connect_scoped()
        self.addCleanup(conn.close)
        contact_id = self._create_old_format_schema(conn)

        db = Database(self.scoped_dsn)
        self.addCleanup(db.close)
        db.ensure_schema()

        media_id = db.insert_media_file(
            contact_id=contact_id,
            canal="whatsapp",
            tipo="audio",
            mime_type="audio/ogg",
            storage_key="whatsapp/2026/08/1/a.ogg",
            origem_media_id="MEDIA_ID",
        )
        db.save_message(
            contact_id,
            direction="in",
            text="",
            canal="whatsapp",
            message_id="wamid.new-1",
            payload={"type": "audio"},
            media_id=media_id,
        )

        messages = db.get_conversation(contact_id, limit=10)
        newest = messages[0]
        self.assertEqual(newest.canal, "whatsapp")
        self.assertEqual(newest.message_id, "wamid.new-1")
        self.assertEqual(newest.payload, {"type": "audio"})
        self.assertEqual(newest.media_id, media_id)

        # Reentrega do mesmo (canal, message_id): não duplica a linha.
        db.save_message(
            contact_id,
            direction="in",
            text="",
            canal="whatsapp",
            message_id="wamid.new-1",
            payload={"type": "audio"},
        )
        messages_after_redelivery = db.get_conversation(contact_id, limit=10)
        self.assertEqual(len(messages_after_redelivery), len(messages))


if __name__ == "__main__":
    unittest.main()
