import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from whatbot.channels import INSTAGRAM, WHATSAPP
from whatbot.priority import calcular_prioridade_handover, prioridade_label
from whatbot.queue import (
    build_daily_summary,
    format_waiting_list,
    normalize_phone,
    notify_assumption,
    process_new_handover,
)
from whatbot.db import WaitingContact
from whatbot.webhook import parse_outgoing_staff_message

from fakes import FakeClient, FakeDatabase


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

    def test_format_shows_whatsapp_channel_label(self):
        """`format_waiting_list` (the `#fila` listing) must name the channel
        next to each contact, not just the identity chip
        (channel-queue-visibility)."""
        contacts = [
            WaitingContact(
                id=1,
                phone="5511888888888",
                push_name="Maria",
                handover_at=datetime.now(timezone.utc),
                handover_motivo="pedido_do_cliente",
                minutes_waiting=5,
                prioridade=0,
                assumido_por=None,
                canal=WHATSAPP,
            )
        ]
        text = format_waiting_list(contacts, "Fila")
        self.assertIn("WhatsApp", text)

    def test_format_shows_instagram_channel_label(self):
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
        self.assertIn("Instagram", text)


class TestNotifyAssumptionShowsChannel(unittest.TestCase):
    """`notify_assumption` ("atendimento assumido") must name the channel
    (channel-queue-visibility)."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001,5511900000002"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_whatsapp_contact_shows_whatsapp(self):
        contact = WaitingContact(
            id=1,
            phone="5511888888888",
            push_name="Maria",
            handover_at=datetime.now(timezone.utc),
            handover_motivo="pedido_do_cliente",
            minutes_waiting=5,
            prioridade=0,
            assumido_por="5511900000001",
            canal=WHATSAPP,
        )
        router = FakeClient(WHATSAPP)

        notify_assumption(router, "5511900000001", contact)

        self.assertTrue(router.sent)
        self.assertIn("WhatsApp", router.sent[0]["text"])

    def test_instagram_contact_shows_instagram(self):
        contact = WaitingContact(
            id=1,
            phone=None,
            push_name="Maria IG",
            handover_at=datetime.now(timezone.utc),
            handover_motivo="pedido_do_cliente",
            minutes_waiting=2,
            prioridade=0,
            assumido_por="5511900000001",
            canal=INSTAGRAM,
            external_id="17841400000000000",
            handle="@maria_ig",
        )
        router = FakeClient(WHATSAPP)

        notify_assumption(router, "5511900000001", contact)

        self.assertTrue(router.sent)
        self.assertIn("Instagram", router.sent[0]["text"])


class TestBuildDailySummaryShowsChannelBreakdown(unittest.TestCase):
    """`build_daily_summary` ("Ainda na fila") must break the still-waiting
    count down by channel (channel-queue-visibility)."""

    def test_summary_lists_waiting_contacts_by_channel(self):
        db = FakeDatabase()
        wa_contact = db.create_contact(phone="5511888888888", push_name="Maria")
        db.enroll_handover(wa_contact.id, motivo="pedido_do_cliente")
        ig_contact = db.create_contact(
            canal=INSTAGRAM, external_id="17841400000000000", handle="@maria_ig"
        )
        db.enroll_handover(ig_contact.id, motivo="pedido_do_cliente")

        summary = build_daily_summary(db)

        self.assertIn("Ainda na fila", summary)
        self.assertIn("WhatsApp: 1", summary)
        self.assertIn("Instagram: 1", summary)


class TestProcessNewHandoverShowsChannel(unittest.TestCase):
    """Immediate handover notification names the channel, not just the label
    (channel-queue-visibility)."""

    def setUp(self):
        self.db = FakeDatabase()
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_whatsapp_contact_shows_whatsapp(self):
        contact = self.db.create_contact(phone="5511888888888", push_name="Maria")
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")
        waiting = self.db.get_contact_waiting("5511888888888")
        router = FakeClient(WHATSAPP)

        process_new_handover(self.db, router, contact=waiting)

        self.assertTrue(router.sent)
        self.assertIn("WhatsApp", router.sent[0]["text"])

    def test_instagram_contact_shows_instagram(self):
        contact = self.db.create_contact(
            canal=INSTAGRAM, external_id="17841400000000000", handle="@maria_ig"
        )
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")
        waiting = self.db.get_contact_waiting(
            "17841400000000000", canal=INSTAGRAM
        )
        router = FakeClient(WHATSAPP)

        process_new_handover(self.db, router, contact=waiting)

        self.assertTrue(router.sent)
        self.assertIn("Instagram", router.sent[0]["text"])
        self.assertIn("@maria_ig", router.sent[0]["text"])


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
