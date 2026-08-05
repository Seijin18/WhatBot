"""`Database.set_contact_tipo_cliente` — closed-set validation
(contact-segmentation-b2b-b2c). Validation runs in Python before
`init_pool()`/any network call (same style as `set_contact_status`), so this
is safe to exercise against a real `Database` instance without a live
Postgres: an invalid value must raise before ever touching the connection
pool."""

import unittest

from whatbot.db import CONTACT_TIPO_CLIENTES, Database


class TestSetContactTipoClienteValidation(unittest.TestCase):
    def setUp(self):
        # Never actually connects: validation short-circuits before
        # `init_pool()` for every value exercised here.
        self.db = Database(dsn="postgresql://unused:unused@localhost/unused")

    def test_rejects_a_value_outside_the_closed_set(self):
        with self.assertRaises(ValueError):
            self.db.set_contact_tipo_cliente(1, "vip")

    def test_error_mentions_the_rejected_value(self):
        with self.assertRaises(ValueError) as ctx:
            self.db.set_contact_tipo_cliente(1, "empresa")

        self.assertIn("empresa", str(ctx.exception))

    def test_closed_set_matches_the_spec(self):
        self.assertEqual(CONTACT_TIPO_CLIENTES, {"b2c", "b2b"})


if __name__ == "__main__":
    unittest.main()
