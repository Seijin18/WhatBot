"""Tests for the Instagram channel client (`whatbot/channels/instagram.py`).

Follows the same no-network pattern as `tests/test_evolution_client.py`:
`requests.post` and `log_outbound` are mocked, nothing touches the network.
"""

import unittest
from unittest.mock import MagicMock, patch

import requests

from whatbot.channels import INSTAGRAM
from whatbot.channels.base import ChannelError
from whatbot.channels.instagram import (
    CAUSE_MISSING_HUMAN_AGENT_PERMISSION,
    CAUSE_RATE_LIMITED,
    CAUSE_WINDOW_EXPIRED,
    InstagramClient,
    split_text,
)

IGSID = "17841400000000000"


def build_client() -> InstagramClient:
    return InstagramClient(
        access_token="ig-token",
        account_id="ig-account",
        base_url="https://graph.instagram.com/",
    )


def _error_response(status_code, code=None, subcode=None, message="erro", headers=None):
    response = MagicMock(ok=False, status_code=status_code, text=message)
    response.headers = headers or {}
    error = {"message": message}
    if code is not None:
        error["code"] = code
    if subcode is not None:
        error["error_subcode"] = subcode
    response.json.return_value = {"error": error}
    return response


class TestClientContract(unittest.TestCase):
    def test_declares_its_channel(self):
        self.assertEqual(InstagramClient.canal, INSTAGRAM)

    def test_base_url_trailing_slash_is_stripped(self):
        self.assertEqual(build_client().base_url, "https://graph.instagram.com")


class TestSplitText(unittest.TestCase):
    def test_short_text_is_a_single_block(self):
        self.assertEqual(split_text("oi"), ["oi"])

    def test_empty_text_is_a_single_empty_block(self):
        self.assertEqual(split_text(""), [""])

    def test_long_text_is_split_preserving_order(self):
        text = " ".join(f"palavra{i}" for i in range(400))
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


class TestSend(unittest.TestCase):
    def setUp(self):
        self.client = build_client()
        self.response = MagicMock(ok=True)
        self.response.json.return_value = {"message_id": "MSG1"}

        post_patch = patch(
            "whatbot.channels.instagram.requests.post", return_value=self.response
        )
        log_patch = patch("whatbot.channels.instagram.log_outbound")
        self.post = post_patch.start()
        self.log_outbound = log_patch.start()
        self.addCleanup(post_patch.stop)
        self.addCleanup(log_patch.stop)

    def test_builds_the_expected_request(self):
        self.client.send_text(IGSID, "Olá")

        url, = self.post.call_args.args
        kwargs = self.post.call_args.kwargs
        self.assertEqual(url, "https://graph.instagram.com/v23.0/me/messages")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer ig-token")
        self.assertEqual(
            kwargs["json"], {"recipient": {"id": IGSID}, "message": {"text": "Olá"}}
        )
        self.assertEqual(kwargs["timeout"], 10)

    def test_returns_the_api_response(self):
        result = self.client.send_text(IGSID, "Olá")

        self.assertEqual(result, {"message_id": "MSG1"})

    def test_human_agent_adds_message_tag(self):
        self.client.send_text(IGSID, "Olá", human_agent=True)

        payload = self.post.call_args.kwargs["json"]
        self.assertEqual(payload["messaging_type"], "MESSAGE_TAG")
        self.assertEqual(payload["tag"], "HUMAN_AGENT")

    def test_without_human_agent_no_tag_is_sent(self):
        self.client.send_text(IGSID, "Olá")

        payload = self.post.call_args.kwargs["json"]
        self.assertNotIn("messaging_type", payload)
        self.assertNotIn("tag", payload)

    def test_successful_send_is_logged_as_sent(self):
        self.client.send_text(IGSID, "Olá", source="handover", contact_id=7)

        self.log_outbound.assert_called_once()
        args, kwargs = self.log_outbound.call_args
        self.assertEqual(args, (IGSID, "Olá"))
        self.assertEqual(kwargs["canal"], INSTAGRAM)
        self.assertEqual(kwargs["delivery"], "sent")
        self.assertEqual(kwargs["source"], "handover")
        self.assertEqual(kwargs["contact_id"], 7)

    def test_long_message_is_split_into_ordered_blocks(self):
        text = " ".join(f"p{i}" for i in range(600))
        self.client.send_text(IGSID, text)

        sent_texts = [call.kwargs["json"]["message"]["text"] for call in self.post.call_args_list]
        self.assertGreater(len(sent_texts), 1)
        self.assertEqual(" ".join(sent_texts), text)


class TestSimulation(unittest.TestCase):
    def setUp(self):
        post_patch = patch("whatbot.channels.instagram.requests.post")
        log_patch = patch("whatbot.channels.instagram.log_outbound")
        self.post = post_patch.start()
        self.log_outbound = log_patch.start()
        self.addCleanup(post_patch.stop)
        self.addCleanup(log_patch.stop)

    def test_simulated_send_never_touches_the_network(self):
        result = build_client().send_text(IGSID, "Olá", simulated=True)

        self.post.assert_not_called()
        self.assertEqual(result, {"simulated": True})

    def test_simulated_send_is_logged_as_skipped(self):
        build_client().send_text(IGSID, "Olá", simulated=True)

        kwargs = self.log_outbound.call_args.kwargs
        self.assertEqual(kwargs["delivery"], "skipped")
        self.assertTrue(kwargs["simulated"])


class TestFailure(unittest.TestCase):
    def setUp(self):
        self.client = build_client()
        log_patch = patch("whatbot.channels.instagram.log_outbound")
        self.log_outbound = log_patch.start()
        self.addCleanup(log_patch.stop)

    def test_transport_failure_is_a_retryable_channel_error(self):
        with patch(
            "whatbot.channels.instagram.requests.post",
            side_effect=requests.ConnectionError("sem rede"),
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(IGSID, "Olá")

        self.assertEqual(ctx.exception.canal, INSTAGRAM)
        self.assertTrue(ctx.exception.retryable)
        self.assertIsNone(ctx.exception.cause)
        self.assertEqual(self.log_outbound.call_args.kwargs["delivery"], "failed")

    def test_window_expired_is_a_typed_cause(self):
        response = _error_response(400, code=100, subcode=2534014, message="janela expirada")
        with patch(
            "whatbot.channels.instagram.requests.post", return_value=response
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(IGSID, "Olá")

        self.assertEqual(ctx.exception.cause, CAUSE_WINDOW_EXPIRED)
        self.assertFalse(ctx.exception.retryable)

    def test_missing_human_agent_permission_is_a_typed_cause(self):
        response = _error_response(403, code=10, message="permissão ausente")
        with patch(
            "whatbot.channels.instagram.requests.post", return_value=response
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(IGSID, "Olá", human_agent=True)

        self.assertEqual(ctx.exception.cause, CAUSE_MISSING_HUMAN_AGENT_PERMISSION)

    def test_rate_limit_is_a_typed_cause_with_backoff(self):
        response = _error_response(
            429, code=613, message="rate limited", headers={"Retry-After": "30"}
        )
        with patch(
            "whatbot.channels.instagram.requests.post", return_value=response
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(IGSID, "Olá")

        self.assertEqual(ctx.exception.cause, CAUSE_RATE_LIMITED)
        self.assertIn("30", str(ctx.exception))
        self.assertTrue(ctx.exception.retryable)

    def test_rate_limit_without_retry_after_still_typed(self):
        response = _error_response(429, code=613, message="rate limited")
        with patch(
            "whatbot.channels.instagram.requests.post", return_value=response
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(IGSID, "Olá")

        self.assertEqual(ctx.exception.cause, CAUSE_RATE_LIMITED)

    def test_unrecognized_error_has_no_cause_and_is_not_retryable(self):
        response = _error_response(400, code=999, message="algo desconhecido")
        with patch(
            "whatbot.channels.instagram.requests.post", return_value=response
        ):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(IGSID, "Olá")

        self.assertIsNone(ctx.exception.cause)
        self.assertFalse(ctx.exception.retryable)


if __name__ == "__main__":
    unittest.main()
