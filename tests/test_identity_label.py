"""Direct tests for the readable-label contract (requirement "Rótulo legível
de contato", design.md Decisão 8).

`whatbot.db.resolve_label` is the single exported precedence function
(name -> handle -> raw external identity); `Contact.label` and
`WaitingContact.label` are thin wrappers over it. These tests exercise the
two spec scenarios directly, since `format_disambiguation` (exercised in
`test_admin_organic.py`) uses a related but distinct rendering and is not a
substitute for testing `.label` itself.
"""

import unittest
from datetime import datetime, timezone

from whatbot.channels import INSTAGRAM, WHATSAPP
from whatbot.db import Contact, WaitingContact, resolve_label


class TestResolveLabel(unittest.TestCase):
    def test_name_wins_when_present(self):
        self.assertEqual(resolve_label("Maria", "@maria_ig", "12345"), "Maria")

    def test_no_name_uses_handle(self):
        self.assertEqual(resolve_label(None, "@maria_ig", "12345"), "@maria_ig")

    def test_no_name_no_handle_uses_external_id(self):
        self.assertEqual(resolve_label(None, None, "12345"), "12345")

    def test_nothing_set_returns_empty_string(self):
        self.assertEqual(resolve_label(None, None, None), "")


class TestContactLabel(unittest.TestCase):
    def test_contact_without_name_uses_handle(self):
        contact = Contact(
            id=1,
            phone=None,
            status="novo_lead",
            ia_ativa=True,
            created_at=datetime.now(timezone.utc),
            push_name=None,
            canal=INSTAGRAM,
            external_id="17841400000000000",
            handle="@joana_ig",
        )
        self.assertEqual(contact.label, "@joana_ig")

    def test_contact_without_name_or_handle_uses_external_id(self):
        contact = Contact(
            id=1,
            phone=None,
            status="novo_lead",
            ia_ativa=True,
            created_at=datetime.now(timezone.utc),
            push_name=None,
            canal=INSTAGRAM,
            external_id="17841400000000000",
            handle=None,
        )
        self.assertEqual(contact.label, "17841400000000000")

    def test_whatsapp_contact_without_name_falls_back_to_phone(self):
        contact = Contact(
            id=1,
            phone="5511888888888",
            status="novo_lead",
            ia_ativa=True,
            created_at=datetime.now(timezone.utc),
            push_name=None,
            canal=WHATSAPP,
        )
        self.assertEqual(contact.label, "5511888888888")


class TestWaitingContactLabel(unittest.TestCase):
    def test_waiting_contact_without_name_uses_handle(self):
        waiting = WaitingContact(
            id=1,
            phone=None,
            push_name=None,
            handover_at=datetime.now(timezone.utc),
            handover_motivo="pedido",
            minutes_waiting=5,
            canal=INSTAGRAM,
            external_id="17841400000000000",
            handle="@joana_ig",
        )
        self.assertEqual(waiting.label, "@joana_ig")

    def test_waiting_contact_without_name_or_handle_uses_external_id(self):
        waiting = WaitingContact(
            id=1,
            phone=None,
            push_name=None,
            handover_at=datetime.now(timezone.utc),
            handover_motivo="pedido",
            minutes_waiting=5,
            canal=INSTAGRAM,
            external_id="17841400000000000",
            handle=None,
        )
        self.assertEqual(waiting.label, "17841400000000000")


if __name__ == "__main__":
    unittest.main()
