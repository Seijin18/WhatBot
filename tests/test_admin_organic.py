import unittest

from whatbot.admin_nlu import (
    is_casual_test_message,
    parse_admin_intent,
    parse_simulate_command,
)
from whatbot.config import resolve_simulate_phone
from whatbot.contact_resolver import find_waiting_matches
from whatbot.db import WaitingContact
from datetime import datetime, timezone


class TestAdminNlu(unittest.TestCase):
    def test_list_intent(self):
        self.assertEqual(parse_admin_intent("quem ta na fila?").action, "list_queue")

    def test_assume_intent(self):
        intent = parse_admin_intent("assumo a Maria")
        self.assertEqual(intent.action, "assume")
        self.assertIn("maria", intent.query.lower())

    def test_complete_intent(self):
        intent = parse_admin_intent("finalizei com o João")
        self.assertEqual(intent.action, "complete")

    def test_reactivate_intent(self):
        intent = parse_admin_intent("libera o bot para Maria")
        self.assertEqual(intent.action, "reactivate")

    def test_simulate(self):
        phone, msg = parse_simulate_command("#simular 5511888888888 Olá")
        self.assertEqual(phone, "5511888888888")
        self.assertEqual(msg, "Olá")

    def test_casual_test(self):
        self.assertTrue(is_casual_test_message("Teste"))
        self.assertTrue(is_casual_test_message("olá!"))
        self.assertFalse(is_casual_test_message("quem ta na fila?"))

    def test_resolve_simulate_phone_avoids_association(self):
        import os

        os.environ["ASSOCIATION_PHONE"] = "5511949305094"
        os.environ["DEFAULT_TEST_PHONE"] = "5511949305094"
        self.assertEqual(resolve_simulate_phone(None), "5511999999999")
        self.assertEqual(resolve_simulate_phone("5511888888888"), "5511888888888")


class TestContactResolver(unittest.TestCase):
    def test_name_match(self):
        waiting = [
            WaitingContact(
                1, "5511111111111", "Maria Silva", datetime.now(timezone.utc),
                "pedido", 5, 0, None,
            ),
            WaitingContact(
                2, "5511222222222", "Maria Costa", datetime.now(timezone.utc),
                "pedido", 3, 0, None,
            ),
        ]
        matches = find_waiting_matches("maria", waiting)
        self.assertEqual(len(matches), 2)


if __name__ == "__main__":
    unittest.main()
