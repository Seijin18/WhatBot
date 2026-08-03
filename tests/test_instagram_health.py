"""Tests for `whatbot/instagram_health.py`.

Requirement "Alertas de saúde da integração": consecutive send-failure
streak, prolonged webhook silence, and credential expiry — each configurable
threshold, no network, no live Postgres.
"""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from whatbot import instagram_health
from whatbot.channels import INSTAGRAM, WHATSAPP, ChannelRouter

from fakes import FakeClient, FakeDatabase

ADMIN_1 = "5511900000001"
ADMIN_2 = "5511900000002"


class HealthTestCase(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.wa = FakeClient(WHATSAPP)
        self.router = ChannelRouter([self.wa])
        patches = [patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": f"{ADMIN_1},{ADMIN_2}"})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class TestSendFailureMonitor(HealthTestCase):
    def test_streak_below_threshold_does_not_trigger(self):
        monitor = instagram_health.SendFailureMonitor(threshold=5)
        for _ in range(4):
            triggered = monitor.record_failure()
            self.assertFalse(triggered)
        self.assertEqual(monitor.streak, 4)

    def test_streak_reaching_threshold_triggers_exactly_once(self):
        monitor = instagram_health.SendFailureMonitor(threshold=3)
        self.assertFalse(monitor.record_failure())
        self.assertFalse(monitor.record_failure())
        self.assertTrue(monitor.record_failure())
        # Kept failing beyond the threshold: does not re-trigger on every
        # subsequent failure, only the crossing.
        self.assertFalse(monitor.record_failure())

    def test_a_success_in_the_middle_resets_the_streak(self):
        monitor = instagram_health.SendFailureMonitor(threshold=3)
        monitor.record_failure()
        monitor.record_failure()
        monitor.record_success()
        self.assertEqual(monitor.streak, 0)

        self.assertFalse(monitor.record_failure())
        self.assertFalse(monitor.record_failure())
        self.assertTrue(monitor.record_failure())

    def test_default_threshold_reads_from_env(self):
        with patch.dict(os.environ, {"IG_ALERT_FAIL_STREAK": "2"}):
            monitor = instagram_health.SendFailureMonitor()
            self.assertEqual(monitor.threshold, 2)


class TestAlertFailStreak(HealthTestCase):
    def test_alerts_every_admin(self):
        sent = instagram_health.alert_fail_streak(self.router, INSTAGRAM, 5)

        self.assertTrue(sent)
        recipients = {m["to"] for m in self.wa.sent}
        self.assertEqual(recipients, {ADMIN_1, ADMIN_2})
        self.assertIn("5", self.wa.sent[0]["text"])


class TestCheckWebhookSilence(HealthTestCase):
    def test_no_event_ever_recorded_does_not_alert(self):
        alerted = instagram_health.check_webhook_silence(self.db, self.router, INSTAGRAM)
        self.assertFalse(alerted)
        self.assertEqual(self.wa.sent, [])

    def test_recent_event_does_not_alert(self):
        self.db.record_webhook_event(INSTAGRAM, "mid-1")

        alerted = instagram_health.check_webhook_silence(self.db, self.router, INSTAGRAM)

        self.assertFalse(alerted)
        self.assertEqual(self.wa.sent, [])

    def test_prolonged_silence_alerts(self):
        self.db.record_webhook_event(INSTAGRAM, "mid-1")
        old_at = list(self.db.webhook_events.values())[0]
        future = old_at + timedelta(minutes=200)

        with patch.dict(os.environ, {"IG_ALERT_SILENCE_MINUTES": "120"}):
            alerted = instagram_health.check_webhook_silence(
                self.db, self.router, INSTAGRAM, now=future
            )

        self.assertTrue(alerted)
        self.assertTrue(self.wa.sent)

    def test_silence_below_threshold_does_not_alert(self):
        self.db.record_webhook_event(INSTAGRAM, "mid-1")
        old_at = list(self.db.webhook_events.values())[0]
        soon = old_at + timedelta(minutes=30)

        with patch.dict(os.environ, {"IG_ALERT_SILENCE_MINUTES": "120"}):
            alerted = instagram_health.check_webhook_silence(
                self.db, self.router, INSTAGRAM, now=soon
            )

        self.assertFalse(alerted)
        self.assertEqual(self.wa.sent, [])


class TestCheckCredentialExpiry(HealthTestCase):
    def test_no_credential_on_record_does_not_alert(self):
        alerted = instagram_health.check_credential_expiry(self.db, self.router, INSTAGRAM)
        self.assertFalse(alerted)
        self.assertEqual(self.wa.sent, [])

    def test_credential_far_from_expiring_does_not_alert(self):
        now = datetime.now(timezone.utc)
        self.db.upsert_channel_credential(
            INSTAGRAM, "token", expires_at=now + timedelta(days=30)
        )

        alerted = instagram_health.check_credential_expiry(self.db, self.router, INSTAGRAM, now=now)

        self.assertFalse(alerted)
        self.assertEqual(self.wa.sent, [])

    def test_credential_close_to_expiring_alerts(self):
        now = datetime.now(timezone.utc)
        self.db.upsert_channel_credential(
            INSTAGRAM, "token", expires_at=now + timedelta(days=3)
        )

        alerted = instagram_health.check_credential_expiry(self.db, self.router, INSTAGRAM, now=now)

        self.assertTrue(alerted)
        self.assertTrue(self.wa.sent)


if __name__ == "__main__":
    unittest.main()
