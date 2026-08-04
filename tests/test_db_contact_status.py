"""`Database.set_contact_status` — closed-set validation (contact-interest-
memory). Validation runs in Python before `init_pool()`/any network call
(same style as `create_contact`'s `external_id` check), so this is safe to
exercise against a real `Database` instance without a live Postgres: an
invalid value must raise before ever touching the connection pool."""

import unittest

from whatbot.db import CONTACT_STATUSES, Database


class TestSetContactStatusValidation(unittest.TestCase):
    def setUp(self):
        # Never actually connects: validation short-circuits before
        # `init_pool()` for every value exercised here.
        self.db = Database(dsn="postgresql://unused:unused@localhost/unused")

    def test_rejects_a_value_outside_the_closed_set(self):
        with self.assertRaises(ValueError):
            self.db.set_contact_status(1, "vip")

    def test_error_mentions_the_rejected_value(self):
        with self.assertRaises(ValueError) as ctx:
            self.db.set_contact_status(1, "bogus_status")

        self.assertIn("bogus_status", str(ctx.exception))

    def test_closed_set_matches_the_spec(self):
        self.assertEqual(
            CONTACT_STATUSES,
            {"novo_lead", "interessado", "comprando", "cliente_ativo", "cancelado"},
        )


if __name__ == "__main__":
    unittest.main()
