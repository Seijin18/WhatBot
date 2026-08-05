"""Tests for the WhatsApp Cloud API channel client
(`whatbot/channels/whatsapp_cloud.py`).

Follows the same no-network pattern as `tests/test_instagram_client.py`:
`requests.post` and `log_outbound` are mocked, nothing touches the network.
"""

import unittest
from unittest.mock import MagicMock, patch

import requests

from whatbot.channels import WHATSAPP
from whatbot.channels.base import ChannelError
from whatbot.channels.whatsapp_cloud import (
    CAUSE_INVALID_TOKEN,
    CAUSE_NOT_OPTED_IN,
    CAUSE_OUTSIDE_WINDOW,
    CAUSE_RATE_LIMITED,
    WhatsAppCloudClient,
    split_text,
)

PHONE = "5511999998888"


def build_client() -> WhatsAppCloudClient:
    return WhatsAppCloudClient(
        access_token="wa-token",
        phone_number_id="1234567890",
        base_url="https://graph.facebook.com/",
    )


def _error_response(status_code, code=None, message="erro", headers=None):
    response = MagicMock(ok=False, status_code=status_code, text=message)
    response.headers = headers or {}
    error = {"message": message}
    if code is not None:
        error["code"] = code
    response.json.return_value = {"error": error}
    return response


class TestClientContract(unittest.TestCase):
    def test_declares_its_channel(self):
        # Same canal as EvolutionApiClient — see design.md "Decisão: mesmo
        # canal whatsapp": WhatsAppCloudClient replaces it, not adds a new one.
        self.assertEqual(WhatsAppCloudClient.canal, WHATSAPP)

    def test_base_url_trailing_slash_is_stripped(self):
        self.assertEqual(build_client().base_url, "https://graph.facebook.com")


class TestSplitText(unittest.TestCase):
    def test_short_text_is_a_single_block(self):
        self.assertEqual(split_text("oi"), ["oi"])

    def test_empty_text_is_a_single_empty_block(self):
        self.assertEqual(split_text(""), [""])

    def test_long_text_is_split_preserving_order(self):
        text = " ".join(f"palavra{i}" for i in range(1200))
        blocks = split_text(text, limit=50)

        self.assertGreater(len(blocks), 1)
        for block in blocks:
            self.assertLessEqual(len(block), 50)
        self.assertEqual(" ".join(blocks), text)

    def test_word_longer_than_limit_is_hard_cut(self):
        text = "a" * 30
        blocks = split_text(text, limit=10)

        self.assertEqual("".join(blocks), text)
        for block in blocks:
            self.assertLessEqual(len(block), 10)

    def test_non_positive_limit_does_not_loop_forever(self):
        blocks = split_text("abc", limit=0)

        self.assertEqual("".join(blocks), "abc")
        self.assertTrue(all(len(b) <= 1 for b in blocks))

    def test_typical_reply_stays_a_single_block(self):
        # The whole point of the 4096 limit vs Instagram's 1000: an ordinary
        # bot reply should never actually trigger splitting in practice.
        text = "Olá! " * 200  # ~1000 chars
        self.assertEqual(len(split_text(text)), 1)


class TestSend(unittest.TestCase):
    def setUp(self):
        self.client = build_client()
        self.response = MagicMock(ok=True)
        self.response.json.return_value = {"messages": [{"id": "wamid.MSG1"}]}

        post_patch = patch(
            "whatbot.channels.whatsapp_cloud.requests.post", return_value=self.response
        )
        log_patch = patch("whatbot.channels.whatsapp_cloud.log_outbound")
        self.post = post_patch.start()
        self.log_outbound = log_patch.start()
        self.addCleanup(post_patch.stop)
        self.addCleanup(log_patch.stop)

    def test_builds_the_expected_request(self):
        self.client.send_text(PHONE, "Olá")

        (url,) = self.post.call_args.args
        kwargs = self.post.call_args.kwargs
        self.assertEqual(
            url, "https://graph.facebook.com/v25.0/1234567890/messages"
        )
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer wa-token")
        self.assertEqual(
            kwargs["json"],
            {
                "messaging_product": "whatsapp",
                "to": PHONE,
                "type": "text",
                "text": {"body": "Olá"},
            },
        )
        self.assertEqual(kwargs["timeout"], 10)

    def test_returns_the_api_response(self):
        result = self.client.send_text(PHONE, "Olá")

        self.assertEqual(result, {"messages": [{"id": "wamid.MSG1"}]})

    def test_human_agent_is_accepted_and_ignored(self):
        # WhatsApp Cloud has no messaging-window/tag concept — human_agent is
        # accepted (keyword compatibility with ChannelClient) but has no
        # effect on the payload, unlike InstagramClient.
        self.client.send_text(PHONE, "Olá", human_agent=True)

        payload = self.post.call_args.kwargs["json"]
        self.assertNotIn("messaging_type", payload)
        self.assertNotIn("tag", payload)

    def test_successful_send_is_logged_as_sent(self):
        self.client.send_text(PHONE, "Olá", source="handover", contact_id=7)

        self.log_outbound.assert_called_once()
        args, kwargs = self.log_outbound.call_args
        self.assertEqual(args, (PHONE, "Olá"))
        self.assertEqual(kwargs["canal"], WHATSAPP)
        self.assertEqual(kwargs["delivery"], "sent")
        self.assertEqual(kwargs["source"], "handover")
        self.assertEqual(kwargs["contact_id"], 7)


class TestSimulation(unittest.TestCase):
    def setUp(self):
        post_patch = patch("whatbot.channels.whatsapp_cloud.requests.post")
        log_patch = patch("whatbot.channels.whatsapp_cloud.log_outbound")
        self.post = post_patch.start()
        self.log_outbound = log_patch.start()
        self.addCleanup(post_patch.stop)
        self.addCleanup(log_patch.stop)

    def test_simulated_send_never_touches_the_network(self):
        result = build_client().send_text(PHONE, "Olá", simulated=True)

        self.post.assert_not_called()
        self.assertEqual(result, {"simulated": True})

    def test_simulated_send_is_logged_as_skipped(self):
        build_client().send_text(PHONE, "Olá", simulated=True)

        kwargs = self.log_outbound.call_args.kwargs
        self.assertEqual(kwargs["delivery"], "skipped")
        self.assertTrue(kwargs["simulated"])


class TestFailure(unittest.TestCase):
    def setUp(self):
        self.client = build_client()
        log_patch = patch("whatbot.channels.whatsapp_cloud.log_outbound")
        self.log_outbound = log_patch.start()
        self.addCleanup(log_patch.stop)

    def test_transport_failure_is_a_retryable_channel_error(self):
        with patch(
            "whatbot.channels.whatsapp_cloud.requests.post",
            side_effect=requests.ConnectionError("sem rede"),
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(PHONE, "Olá")

        self.assertEqual(ctx.exception.canal, WHATSAPP)
        self.assertTrue(ctx.exception.retryable)
        self.assertIsNone(ctx.exception.cause)
        self.assertEqual(self.log_outbound.call_args.kwargs["delivery"], "failed")

    def test_invalid_token_is_a_typed_cause(self):
        response = _error_response(401, code=190, message="token expirado")
        with patch(
            "whatbot.channels.whatsapp_cloud.requests.post", return_value=response
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(PHONE, "Olá")

        self.assertEqual(ctx.exception.cause, CAUSE_INVALID_TOKEN)
        self.assertFalse(ctx.exception.retryable)

    def test_outside_window_is_a_typed_cause(self):
        response = _error_response(
            470, code=131047, message="mais de 24h desde a última resposta"
        )
        with patch(
            "whatbot.channels.whatsapp_cloud.requests.post", return_value=response
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(PHONE, "Olá")

        self.assertEqual(ctx.exception.cause, CAUSE_OUTSIDE_WINDOW)
        self.assertFalse(ctx.exception.retryable)

    def test_not_opted_in_is_a_typed_cause(self):
        response = _error_response(470, code=131026, message="destinatário indisponível")
        with patch(
            "whatbot.channels.whatsapp_cloud.requests.post", return_value=response
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(PHONE, "Olá")

        self.assertEqual(ctx.exception.cause, CAUSE_NOT_OPTED_IN)
        self.assertFalse(ctx.exception.retryable)

    def test_rate_limit_is_a_typed_cause_with_backoff(self):
        response = _error_response(
            429, code=80007, message="rate limited", headers={"Retry-After": "30"}
        )
        with patch(
            "whatbot.channels.whatsapp_cloud.requests.post", return_value=response
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(PHONE, "Olá")

        self.assertEqual(ctx.exception.cause, CAUSE_RATE_LIMITED)
        self.assertIn("30", str(ctx.exception))
        self.assertTrue(ctx.exception.retryable)

    def test_rate_limit_without_retry_after_still_typed(self):
        response = _error_response(429, code=80007, message="rate limited")
        with patch(
            "whatbot.channels.whatsapp_cloud.requests.post", return_value=response
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(PHONE, "Olá")

        self.assertEqual(ctx.exception.cause, CAUSE_RATE_LIMITED)

    def test_unrecognized_error_has_no_cause_and_is_not_retryable(self):
        response = _error_response(400, code=999999, message="algo desconhecido")
        with patch(
            "whatbot.channels.whatsapp_cloud.requests.post", return_value=response
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(PHONE, "Olá")

        self.assertIsNone(ctx.exception.cause)
        self.assertFalse(ctx.exception.retryable)


if __name__ == "__main__":
    unittest.main()
