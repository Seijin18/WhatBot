import unittest
from datetime import datetime, timedelta, timezone

from whatbot.channels import INSTAGRAM
from whatbot.priority import calcular_prioridade_handover, prioridade_label
from whatbot.queue import format_waiting_list, normalize_phone
from whatbot.db import WaitingContact
from whatbot.webhook import parse_outgoing_staff_message

from fakes import FakeDatabase


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

    def test_format_tolerates_contact_without_phone(self):
        """Non-WhatsApp contacts have `phone=None` (design.md, Decisão 3)."""
        contacts = [
            WaitingContact(
                id=1,
                phone=None,
                push_name="Maria IG",
                handover_at=datetime.now(timezone.utc),
                handover_motivo="pedido_do_cliente",
                minutes_waiting=2,
                prioridade=0,
                assumido_por=None,
                canal=INSTAGRAM,
                external_id="17841400000000000",
                handle="@maria_ig",
            )
        ]
        text = format_waiting_list(contacts, "Fila")
        self.assertIn("Maria IG", text)
        # Identity chip uses the unified precedence (handle -> external_id,
        # see whatbot/db.py:resolve_label) — handle wins here.
        self.assertIn("@maria_ig", text)


class TestProcessAutoReactivations(unittest.TestCase):
    """`process_auto_reactivations` with `phone=None` must not break
    (design.md, Importante 6 / tasks.md 6.5) — a real call, not just a name
    referenced from `fakes.py`."""

    def test_reactivates_a_non_whatsapp_contact_without_phone(self):
        db = FakeDatabase()
        contact = db.create_contact(
            canal=INSTAGRAM, external_id="17841400000000000", handle="@maria_ig"
        )
        db.contacts[contact.id]["ia_ativa"] = False
        db.contacts[contact.id]["bot_resume_at"] = datetime.now(timezone.utc) - timedelta(
            hours=1
        )

        reactivated = db.process_auto_reactivations()

        self.assertEqual(reactivated, ["@maria_ig"])
        self.assertTrue(db.contacts[contact.id]["ia_ativa"])
        self.assertIsNone(db.contacts[contact.id]["bot_resume_at"])


if __name__ == "__main__":
    unittest.main()
