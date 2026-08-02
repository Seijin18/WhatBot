"""Tests for the Instagram messaging window (24h / 7-day human-agent policy).

Covers `whatbot/channels/instagram.py::InstagramClient.send_text` (Requirement
"Janela de mensageria de 24 horas") and `whatbot/queue.py::window_deadline_note`
plus `process_new_handover` (Requirement "Notificação de fila informa prazo de
resposta"). The clock is injected — see `design.md` in
`openspec/changes/instagram-messaging-window/` for why — so nothing here
depends on wall-clock time.
"""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from whatbot.channels import INSTAGRAM, WHATSAPP, ChannelRouter
from whatbot.channels.base import ChannelError
from whatbot.channels.instagram import (
    CAUSE_WINDOW_CHECK_UNAVAILABLE,
    CAUSE_WINDOW_EXPIRED,
    InstagramClient,
)
from whatbot.queue import process_new_handover, run_periodic_queue_checks, window_deadline_note

from fakes import FakeClient, FakeDatabase

IGSID = "17841400000000000"
NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def build_client(last_inbound_at, *, now=NOW):
    return InstagramClient(
        access_token="ig-token",
        last_inbound_lookup=lambda to: last_inbound_at,
        clock=lambda: now,
    )


class TestMessagingWindowEnforcement(unittest.TestCase):
    """`InstagramClient.send_text` before dispatching any HTTP call."""

    def setUp(self):
        post_patch = patch("whatbot.channels.instagram.requests.post")
        log_patch = patch("whatbot.channels.instagram.log_outbound")
        self.post = post_patch.start()
        self.log_outbound = log_patch.start()
        self.addCleanup(post_patch.stop)
        self.addCleanup(log_patch.stop)
        response = MagicMock(ok=True)
        response.json.return_value = {"message_id": "MSG1"}
        self.post.return_value = response

    def test_send_within_24h_goes_through(self):
        client = build_client(NOW - timedelta(hours=1))

        result = client.send_text(IGSID, "Olá")

        self.post.assert_called_once()
        self.assertEqual(result, {"message_id": "MSG1"})

    def test_send_between_24h_and_7_days_is_blocked_without_human_agent(self):
        client = build_client(NOW - timedelta(days=2))

        with self.assertRaises(ChannelError) as ctx:
            client.send_text(IGSID, "Olá")

        self.assertEqual(ctx.exception.cause, CAUSE_WINDOW_EXPIRED)
        self.post.assert_not_called()

    def test_send_between_24h_and_7_days_with_human_agent_goes_through(self):
        client = build_client(NOW - timedelta(days=2))

        result = client.send_text(IGSID, "Olá", human_agent=True)

        self.post.assert_called_once()
        self.assertEqual(result, {"message_id": "MSG1"})

    def test_send_past_7_days_is_blocked_even_with_human_agent(self):
        client = build_client(NOW - timedelta(days=8))

        with self.assertRaises(ChannelError) as ctx:
            client.send_text(IGSID, "Olá", human_agent=True)

        self.assertEqual(ctx.exception.cause, CAUSE_WINDOW_EXPIRED)
        self.assertFalse(ctx.exception.retryable)
        self.post.assert_not_called()

    def test_blocked_send_is_logged_as_a_failure_with_a_cause(self):
        client = build_client(NOW - timedelta(days=8))

        with self.assertRaises(ChannelError):
            client.send_text(IGSID, "Olá")

        self.log_outbound.assert_called_once()
        kwargs = self.log_outbound.call_args.kwargs
        self.assertEqual(kwargs["delivery"], "failed")
        self.assertEqual(kwargs["cause"], CAUSE_WINDOW_EXPIRED)

    def test_no_last_inbound_record_is_treated_as_outside_the_window(self):
        client = build_client(None)

        with self.assertRaises(ChannelError) as ctx:
            client.send_text(IGSID, "Olá")

        self.assertEqual(ctx.exception.cause, CAUSE_WINDOW_EXPIRED)
        self.post.assert_not_called()

    def test_without_an_injected_lookup_the_send_is_blocked_fail_closed(self):
        """Fail-closed: a client with no `last_inbound_lookup` never sends,
        rather than skipping the check (Bloqueador 1 do critic — o padrão do
        projeto é falhar travando, nunca falhar liberando)."""
        client = InstagramClient(access_token="ig-token")

        with self.assertRaises(ChannelError) as ctx:
            client.send_text(IGSID, "Olá")

        self.assertEqual(ctx.exception.cause, CAUSE_WINDOW_CHECK_UNAVAILABLE)
        self.post.assert_not_called()

    def test_simulated_send_bypasses_the_window_check(self):
        client = build_client(NOW - timedelta(days=30))

        result = client.send_text(IGSID, "Olá", simulated=True)

        self.post.assert_not_called()
        self.assertEqual(result, {"simulated": True})


class TestReactivationIsNotProactive(unittest.TestCase):
    """Ending a handover flips `ia_ativa` back on but never messages the
    customer — the bot stays purely reactive (design.md, "Não-objetivos")."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_auto_reactivation_notifies_admin_but_never_the_customer(self):
        db = FakeDatabase()
        contact = db.create_contact(canal=INSTAGRAM, external_id=IGSID, handle="@maria_ig")
        db.contacts[contact.id]["ia_ativa"] = False
        db.contacts[contact.id]["bot_resume_at"] = datetime.now(timezone.utc) - timedelta(
            hours=1
        )

        wa = FakeClient(WHATSAPP)
        ig = FakeClient(INSTAGRAM)
        router = ChannelRouter([wa, ig])

        result = run_periodic_queue_checks(db, router)

        self.assertEqual(result["reactivated"], ["@maria_ig"])
        self.assertEqual(ig.sent, [])
        self.assertTrue(db.contacts[contact.id]["ia_ativa"])
        # Admins learn about it (on the admin channel, WhatsApp); the customer
        # only hears from the bot again once they write in.
        admin_sends = [m for m in wa.sent if m["to"] == "5511900000001"]
        self.assertTrue(admin_sends)
        self.assertIn("reativado", admin_sends[0]["text"])


class TestQueueNotificationShowsResponseDeadline(unittest.TestCase):
    """`whatbot/queue.py` — Requirement "Notificação de fila informa prazo de
    resposta", extending the channel-queue-visibility notification."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = FakeDatabase()

    def _waiting_instagram_contact(self, last_inbound_at):
        contact = self.db.create_contact(
            canal=INSTAGRAM, external_id=IGSID, handle="@maria_ig"
        )
        self.db.contacts[contact.id]["last_inbound_at"] = last_inbound_at
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")
        return self.db.get_contact_waiting(IGSID, canal=INSTAGRAM)

    def test_within_24h_shows_the_free_window_deadline(self):
        now = datetime.now(timezone.utc)
        waiting = self._waiting_instagram_contact(now - timedelta(hours=1))

        note = window_deadline_note(waiting, now=now)

        self.assertIsNotNone(note)
        self.assertIn("24h", note)

    def test_between_24h_and_7_days_shows_the_human_agent_deadline(self):
        now = datetime.now(timezone.utc)
        waiting = self._waiting_instagram_contact(now - timedelta(days=2))

        note = window_deadline_note(waiting, now=now)

        self.assertIsNotNone(note)
        self.assertIn("atendimento humano", note)
        self.assertIn("7 dias", note)

    def test_past_7_days_shows_the_window_is_closed(self):
        now = datetime.now(timezone.utc)
        waiting = self._waiting_instagram_contact(now - timedelta(days=8))

        note = window_deadline_note(waiting, now=now)

        self.assertIsNotNone(note)
        self.assertIn("encerrada", note)

    def test_whatsapp_contact_has_no_deadline_note(self):
        contact = self.db.create_contact(phone="5511888888888", push_name="Maria")
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")
        waiting = self.db.get_contact_waiting("5511888888888")

        self.assertIsNone(window_deadline_note(waiting))

    def test_new_handover_notification_includes_the_deadline(self):
        waiting = self._waiting_instagram_contact(datetime.now(timezone.utc))
        router = FakeClient(WHATSAPP)

        process_new_handover(self.db, router, contact=waiting)

        self.assertTrue(router.sent)
        self.assertIn("Prazo de resposta", router.sent[0]["text"])


if __name__ == "__main__":
    unittest.main()
