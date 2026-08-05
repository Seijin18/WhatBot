"""Tests for `ChannelRouter.send_text`'s short retry on a retryable
`ChannelError` (`whatsapp-send-resilience`).

`time.sleep` is patched at the router's module path so the tests run
instantly instead of actually waiting out the backoff.
"""

import unittest
from unittest.mock import MagicMock, patch

from whatbot.channels import WHATSAPP, ChannelError, ChannelRouter


class FakeFlakyClient:
    """A minimal `ChannelClient` whose `send_text` can be scripted to fail
    N times before succeeding (or fail forever), recording every call."""

    canal = WHATSAPP

    def __init__(self, outcomes):
        # Each item is either an exception instance to raise, or a return
        # value to hand back.
        self._outcomes = list(outcomes)
        self.calls = 0

    def send_text(self, to, text, **kwargs):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TestRetryableFailureRecovers(unittest.TestCase):
    def setUp(self):
        sleep_patch = patch("whatbot.channels.router.time.sleep")
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def test_succeeds_on_second_attempt(self):
        client = FakeFlakyClient(
            [
                ChannelError(WHATSAPP, "rede instável", retryable=True),
                {"ok": True},
            ]
        )
        router = ChannelRouter([client])

        result = router.send_text("5511999999999", "oi")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(client.calls, 2)
        self.sleep.assert_called_once()

    def test_non_retryable_error_does_not_retry(self):
        client = FakeFlakyClient(
            [ChannelError(WHATSAPP, "token inválido", retryable=False)]
        )
        router = ChannelRouter([client])

        with self.assertRaises(ChannelError) as ctx:
            router.send_text("5511999999999", "oi")

        self.assertFalse(ctx.exception.retryable)
        self.assertEqual(client.calls, 1)
        self.sleep.assert_not_called()

    def test_exhausting_all_attempts_propagates_the_last_error(self):
        last_error = ChannelError(WHATSAPP, "terceira falha", retryable=True)
        client = FakeFlakyClient(
            [
                ChannelError(WHATSAPP, "primeira falha", retryable=True),
                ChannelError(WHATSAPP, "segunda falha", retryable=True),
                last_error,
            ]
        )
        router = ChannelRouter([client])

        with self.assertRaises(ChannelError) as ctx:
            router.send_text("5511999999999", "oi")

        self.assertIs(ctx.exception, last_error)
        self.assertEqual(client.calls, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_success_on_first_attempt_never_sleeps(self):
        client = FakeFlakyClient([{"ok": True}])
        router = ChannelRouter([client])

        router.send_text("5511999999999", "oi")

        self.sleep.assert_not_called()

    def test_admin_send_also_retries(self):
        client = FakeFlakyClient(
            [
                ChannelError(WHATSAPP, "rede instável", retryable=True),
                {"ok": True},
            ]
        )
        router = ChannelRouter([client])

        result = router.send_admin_text("5511900000001", "aviso")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(client.calls, 2)


if __name__ == "__main__":
    unittest.main()
