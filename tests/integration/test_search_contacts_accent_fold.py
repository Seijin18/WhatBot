"""Integration test for accent-folded name search — not part of `make test`.

`search_contacts_for_admin` now dobra acentos em ambos os lados da
comparação via `unaccent(push_name) ILIKE ...` (Postgres extension), não só
no termo digitado pelo admin — bug pré-existente achado durante a
implementação de contact-segmentation-b2b-b2c, confirmado pré-existente por
`git log -p`. A extensão `unaccent` não existe em `FakeDatabase`, então essa
parte só é exercitável contra um Postgres real (ver openspec/project.md,
"Testes", e `tests/integration/test_identity_migration.py`).

Mesmo mecanismo de skip/isolamento de `test_identity_migration.py`: pulado
quando `WHATBOT_TEST_DSN` não está configurado, e roda contra um schema
descartável para nunca tocar as tabelas `public` reais.

Run explicitly against the `db` service from `docker-compose.yml`, e.g.:

    WHATBOT_TEST_DSN=postgresql://whatbot:whatbot@localhost:5432/whatbot \
        python -m pytest tests/integration/test_search_contacts_accent_fold.py -q
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
    f"{ENV_TEST_DSN} não configurado — teste de fold de acento pulado (requer Postgres real)",
)
class TestSearchContactsAccentFold(unittest.TestCase):
    def setUp(self) -> None:
        self.base_dsn = os.environ[ENV_TEST_DSN]
        self.schema = f"whatbot_accent_fold_test_{uuid.uuid4().hex[:8]}"
        self._admin_conn = psycopg.connect(self.base_dsn, autocommit=True)
        with self._admin_conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA {self.schema}")
        self.addCleanup(self._drop_schema)

        # Dedicated DSN scoping every connection to the disposable schema,
        # so this test never touches the real `public` tables even if run
        # against a shared database (mirrors test_identity_migration.py).
        self.scoped_dsn = (
            f"{self.base_dsn}"
            f"{'&' if '?' in self.base_dsn else '?'}"
            f"options=-csearch_path%3D{self.schema}"
        )
        self.db = Database(self.scoped_dsn)
        self.addCleanup(self.db.close)
        self.db.ensure_schema()

    def _drop_schema(self) -> None:
        with self._admin_conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {self.schema} CASCADE")
        self._admin_conn.close()

    def test_accented_push_name_found_by_unaccented_query(self):
        self.db.create_contact(phone="5511888888888", push_name="João")

        rows = self.db.search_contacts_for_admin("joao")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["push_name"], "João")

    def test_unaccented_push_name_found_by_accented_query(self):
        self.db.create_contact(phone="5511888888888", push_name="Joao")

        rows = self.db.search_contacts_for_admin("joão")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["push_name"], "Joao")


if __name__ == "__main__":
    unittest.main()
