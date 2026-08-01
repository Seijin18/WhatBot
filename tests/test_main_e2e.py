"""End-to-end tests at the `main()` seam.

`windmill/f/whatbot/handler.py` calls `whatbot.main.main(payload)` with the raw
Evolution API body, so entering through the same door covers the real path:
payload parsing, admin routing, the domain modules and the outbound router.

These are the only tests that exercise the `whatsapp` -> `router` rename across
`main`, `domain`, `queue` and `admin` — every one of those modules is otherwise
reachable only with a live Postgres.
"""

import os
import unittest
from unittest.mock import patch

from whatbot import main as main_mod
from whatbot.channels import INSTAGRAM, WHATSAPP, ChannelRouter

from fakes import FakeClient, FakeDatabase, FakeLlm

ADMIN_PHONE = "5511900000001"
CUSTOMER_PHONE = "5511999999999"
IGSID = "17841400000000000"

BASE_ENV = {
    "ADMIN_NOTIFY_PHONES": ADMIN_PHONE,
    "TEST_MODE": "false",
    "GEMINI_API_KEY": "test-key",
}


def evolution_payload(phone: str, text: str, push_name: str = "Maria") -> dict:
    """A customer message exactly as the Evolution API webhook delivers it."""
    return {
        "event": "messages.upsert",
        "instance": "whatbot",
        "data": {
            "key": {
                "remoteJid": f"{phone}@s.whatsapp.net",
                "fromMe": False,
                "id": "MSG1",
            },
            "pushName": push_name,
            "message": {"conversation": text},
        },
    }


def staff_reply_payload(phone: str, text: str = "Oi, já te respondo") -> dict:
    """A `fromMe` message: the secretariat answering from WhatsApp Business."""
    return {
        "event": "messages.upsert",
        "instance": "whatbot",
        "data": {
            "key": {
                "remoteJid": f"{phone}@s.whatsapp.net",
                "fromMe": True,
                "id": "MSG2",
            },
            "message": {"conversation": text},
        },
    }


class MainE2ETestCase(unittest.TestCase):
    """Wires the module globals to fakes and neutralizes infra bootstrap."""

    llm_reply = "Temos judô, natação e ginástica. Passe na secretaria para detalhes."
    llm_unavailable = False

    def setUp(self):
        self.db = FakeDatabase()
        self.wa = FakeClient(WHATSAPP)
        self.ig = FakeClient(INSTAGRAM)
        self.router = ChannelRouter([self.wa, self.ig])
        self.llm = FakeLlm(reply=self.llm_reply, unavailable=self.llm_unavailable)

        patches = [
            patch.object(main_mod, "_db", self.db),
            patch.object(main_mod, "_router", self.router),
            patch.object(main_mod, "_llm", self.llm),
            patch.object(main_mod, "_init_infra", lambda: None),
            patch.dict(os.environ, BASE_ENV, clear=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    # -- helpers ---------------------------------------------------------

    def customer_sends(self, text: str, phone: str = CUSTOMER_PHONE) -> dict:
        return main_mod.main(evolution_payload(phone, text))

    def texts_sent_on(self, client: FakeClient) -> list[str]:
        return [m["text"] for m in client.sent]

    def assert_nothing_sent_on(self, client: FakeClient) -> None:
        self.assertEqual(client.sent, [], f"nada deveria sair por {client.canal}")


class TestCustomerReply(MainE2ETestCase):
    def test_evolution_payload_reaches_the_whatsapp_client(self):
        result = self.customer_sends("Quais modalidades vocês têm?")

        self.assertTrue(result["ok"])
        self.assertTrue(result["sent"])
        self.assertEqual(len(self.wa.sent), 1)
        self.assertEqual(self.wa.sent[0]["to"], CUSTOMER_PHONE)
        self.assertEqual(self.wa.sent[0]["source"], "bot")
        self.assertTrue(self.wa.sent[0]["text"])
        self.assert_nothing_sent_on(self.ig)

    def test_contact_and_messages_are_persisted(self):
        self.customer_sends("Quais modalidades vocês têm?")

        contact = self.db.get_contact_by_phone(CUSTOMER_PHONE)
        self.assertIsNotNone(contact)
        self.assertEqual(contact.push_name, "Maria")
        directions = [m["direction"] for m in self.db.messages]
        self.assertEqual(directions, ["in", "out"])

    def test_inactive_bot_short_circuits_without_sending(self):
        contact = self.db.create_contact(phone=CUSTOMER_PHONE, ia_ativa=False)
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")

        result = self.customer_sends("ainda estou esperando")

        self.assertTrue(result["handed_to_human"])
        self.assert_nothing_sent_on(self.wa)


class TestChannelRouting(MainE2ETestCase):
    """The invariant from the plan: customer on their channel, admin on WhatsApp."""

    def test_customer_on_another_channel_is_answered_there(self):
        result = main_mod.process_customer_message(
            IGSID, "Quais modalidades vocês têm?", canal=INSTAGRAM
        )

        self.assertTrue(result["ok"])
        self.assertEqual(len(self.ig.sent), 1)
        self.assertEqual(self.ig.sent[0]["to"], IGSID)
        self.assert_nothing_sent_on(self.wa)

    def test_handover_answers_customer_on_channel_and_admin_on_whatsapp(self):
        result = main_mod.process_customer_message(
            IGSID, "quero falar com a secretaria", canal=INSTAGRAM
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["handed_to_human"])

        # Customer got the handover confirmation on Instagram.
        self.assertEqual(len(self.ig.sent), 1)
        self.assertEqual(self.ig.sent[0]["source"], "handover")
        self.assertTrue(self.ig.sent[0]["human_agent"])

        # Secretariat was notified on WhatsApp, never on Instagram.
        self.assertTrue(self.wa.sent)
        admin_sends = [m for m in self.wa.sent if m["to"] == ADMIN_PHONE]
        self.assertTrue(admin_sends)
        self.assertIn("Novo na fila", admin_sends[0]["text"])

    def test_handover_on_whatsapp_notifies_admin_and_customer(self):
        result = self.customer_sends("quero falar com a secretaria")

        self.assertTrue(result["handed_to_human"])
        recipients = {m["to"] for m in self.wa.sent}
        self.assertEqual(recipients, {CUSTOMER_PHONE, ADMIN_PHONE})
        self.assert_nothing_sent_on(self.ig)

    def test_handover_puts_contact_in_queue(self):
        self.customer_sends("quero falar com a secretaria")

        waiting = self.db.get_waiting_contacts()
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0].phone, CUSTOMER_PHONE)


class TestAdminCommands(MainE2ETestCase):
    def test_admin_assume_replies_on_admin_channel(self):
        contact = self.db.create_contact(phone=CUSTOMER_PHONE, push_name="Maria")
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")

        result = main_mod.main(
            evolution_payload(ADMIN_PHONE, "assumir Maria", push_name="Secretaria")
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["admin_command"])
        self.assertIn("assumiu", result["reply"])

        waiting = self.db.get_contact_waiting(CUSTOMER_PHONE)
        self.assertEqual(waiting.assumido_por, ADMIN_PHONE)

        confirmations = [m for m in self.wa.sent if m["to"] == ADMIN_PHONE]
        self.assertTrue(confirmations)
        self.assert_nothing_sent_on(self.ig)

    def test_admin_queue_listing_reaches_the_admin(self):
        contact = self.db.create_contact(phone=CUSTOMER_PHONE, push_name="Maria")
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")

        result = main_mod.main(evolution_payload(ADMIN_PHONE, "fila"))

        self.assertTrue(result["admin_command"])
        self.assertEqual(self.wa.sent[-1]["to"], ADMIN_PHONE)
        self.assertEqual(self.wa.sent[-1]["source"], "admin")


class TestStaffOutgoing(MainE2ETestCase):
    def test_staff_reply_auto_completes_the_queue_entry(self):
        contact = self.db.create_contact(phone=CUSTOMER_PHONE, push_name="Maria")
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")

        result = main_mod.main(staff_reply_payload(CUSTOMER_PHONE))

        self.assertTrue(result["ok"])
        self.assertTrue(result["auto_attended"])
        self.assertIsNone(self.db.get_contact_waiting(CUSTOMER_PHONE))

        admin_sends = [m for m in self.wa.sent if m["to"] == ADMIN_PHONE]
        self.assertTrue(admin_sends)
        self.assertIn("atendido via WhatsApp Business", admin_sends[0]["text"])

    def test_staff_reply_to_unknown_contact_is_ignored(self):
        result = main_mod.main(staff_reply_payload("5511888888888"))

        self.assertTrue(result["ignored"])
        self.assert_nothing_sent_on(self.wa)


class TestUnsupportedChannel(MainE2ETestCase):
    """D2 — a channel the app cannot handle stops at the edge."""

    def test_payload_with_unknown_channel_is_refused(self):
        result = main_mod.main(
            {"canal": "telegram", "from_number": CUSTOMER_PHONE, "text": "oi"}
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unsupported_channel")
        self.assertIn("telegram", result["detail"])

    def test_nothing_is_touched_when_the_channel_is_refused(self):
        main_mod.main(
            {"canal": "telegram", "from_number": CUSTOMER_PHONE, "text": "oi"}
        )

        self.assertEqual(self.db.contacts, {})
        self.assertEqual(self.llm.calls, [])
        self.assert_nothing_sent_on(self.wa)
        self.assert_nothing_sent_on(self.ig)


class TestAdminSimulation(MainE2ETestCase):
    """D1 — a simulation must carry the simulated contact's channel.

    A simulation never actually messages the customer, so the defect has no
    visible effect today; it is plumbing that only bites once a non-WhatsApp
    contact can be simulated. These tests pin the contract at the seam where
    the channel is handed over.
    """

    def test_simulation_forwards_the_channel(self):
        with patch.object(main_mod, "process_customer_message") as process:
            process.return_value = {"ok": True, "model_reply": "resposta"}
            main_mod.run_admin_simulation(
                ADMIN_PHONE, IGSID, "Quais modalidades?", canal=INSTAGRAM
            )

        self.assertEqual(process.call_args.kwargs["canal"], INSTAGRAM)

    def test_simulation_without_a_channel_defaults_to_whatsapp(self):
        with patch.object(main_mod, "process_customer_message") as process:
            process.return_value = {"ok": True, "model_reply": "resposta"}
            main_mod.run_admin_simulation(ADMIN_PHONE, CUSTOMER_PHONE, "oi")

        self.assertEqual(process.call_args.kwargs["canal"], WHATSAPP)

    def test_simulation_reports_back_on_the_admin_channel(self):
        result = main_mod.run_admin_simulation(
            ADMIN_PHONE, IGSID, "Quais modalidades?", canal=INSTAGRAM
        )

        self.assertEqual(result["simulated_as"], IGSID)
        # The simulated customer is never really messaged...
        self.assert_nothing_sent_on(self.ig)
        # ...but the admin gets the transcript back on the admin channel.
        self.assertEqual(len(self.wa.sent), 1)
        self.assertEqual(self.wa.sent[0]["to"], ADMIN_PHONE)
        self.assertEqual(self.wa.sent[0]["source"], "simulation")


class TestQueueMaintenance(MainE2ETestCase):
    def test_check_queue_runs_without_arguments(self):
        """Production calls `check_queue()` bare from a scheduled Windmill job."""
        result = main_mod.check_queue()

        self.assertTrue(result["ok"])
        self.assertIn("long_wait", result)


class TestModelUnavailable(MainE2ETestCase):
    llm_unavailable = True

    def test_unavailable_model_still_answers_on_the_right_channel(self):
        result = main_mod.process_customer_message(
            IGSID, "Vocês têm natação infantil?", canal=INSTAGRAM
        )

        # Either the knowledge fallback answers or the system notice goes out,
        # but whichever it is must reach the customer on their own channel.
        if result.get("ok"):
            self.assertEqual(len(self.ig.sent), 1)
        else:
            self.assertEqual(self.ig.sent[0]["source"], "system")
            self.assertIn(main_mod.MODEL_UNAVAILABLE_MSG, self.texts_sent_on(self.ig))
        self.assert_nothing_sent_on(self.wa)


if __name__ == "__main__":
    unittest.main()
