import unittest
from datetime import datetime, timezone

from whatbot.priority import calcular_prioridade_handover, prioridade_label
from whatbot.queue import format_waiting_list, normalize_phone
from whatbot.db import WaitingContact
from whatbot.webhook import parse_outgoing_staff_message


class TestPriority(unittest.TestCase):
    def test_alta_prioridade_matricula(self):
        self.assertEqual(calcular_prioridade_handover("Quero fazer matrícula de judô"), 1)

    def test_prioridade_normal(self):
        self.assertEqual(calcular_prioridade_handover("Qual o horário?"), 0)

    def test_prioridade_label(self):
        self.assertEqual(prioridade_label(1), "🔥 ALTA")


class TestOutgoingWebhook(unittest.TestCase):
    def test_parse_outgoing_staff_message(self):
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "5511999999999@s.whatsapp.net",
                    "fromMe": True,
                    "id": "ABC",
                },
                "message": {"conversation": "Olá, sou da secretaria"},
            },
        }
        parsed = parse_outgoing_staff_message(payload)
        self.assertEqual(parsed["to_number"], "5511999999999")
        self.assertTrue(parsed["from_me"])


class TestQueueFormat(unittest.TestCase):
    def test_format_includes_priority_and_assumido(self):
        contacts = [
            WaitingContact(
                id=1,
                phone="5511888888888",
                push_name="Maria",
                handover_at=datetime.now(timezone.utc),
                handover_motivo="pedido_do_cliente",
                minutes_waiting=5,
                prioridade=1,
                assumido_por="5511777777777",
            )
        ]
        text = format_waiting_list(contacts, "Fila")
        self.assertIn("ALTA", text)
        self.assertIn("5511777777777", text)


if __name__ == "__main__":
    unittest.main()
