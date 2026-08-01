"""Tests for the WhatsApp channel client.

The class was moved between modules and gained a `human_agent` kwarg in the
channels refactor without a single test covering it — not the request it builds,
not the outbound logging, not the failure path.
"""

import unittest
from unittest.mock import MagicMock, patch

import requests

from whatbot.channels import WHATSAPP
from whatbot.channels.whatsapp_evolution import EvolutionApiClient

PHONE = "5511999999999"


def build_client() -> EvolutionApiClient:
    return EvolutionApiClient(
        api_key="secret-key",
        instance_name="whatbot",
        base_url="http://evolution-api:8080/",
    )


class TestClientContract(unittest.TestCase):
    def test_declares_its_channel(self):
        self.assertEqual(EvolutionApiClient.canal, WHATSAPP)

    def test_base_url_trailing_slash_is_stripped(self):
        self.assertEqual(build_client().base_url, "http://evolution-api:8080")


class TestSend(unittest.TestCase):
    def setUp(self):
        self.client = build_client()
        self.response = MagicMock(ok=True)
        self.response.json.return_value = {"key": {"id": "MSG1"}}

        post_patch = patch(
            "whatbot.channels.whatsapp_evolution.requests.post",
            return_value=self.response,
        )
        log_patch = patch("whatbot.channels.whatsapp_evolution.log_outbound")
        self.post = post_patch.start()
        self.log_outbound = log_patch.start()
        self.addCleanup(post_patch.stop)
        self.addCleanup(log_patch.stop)

    def test_builds_the_expected_request(self):
        self.client.send_text(PHONE, "Olá")

        url, = self.post.call_args.args
        kwargs = self.post.call_args.kwargs
        self.assertEqual(url, "http://evolution-api:8080/message/sendText/whatbot")
        self.assertEqual(kwargs["headers"]["apikey"], "secret-key")
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(kwargs["json"], {"number": PHONE, "text": "Olá"})
        self.assertEqual(kwargs["timeout"], 10)

    def test_returns_the_api_response(self):
        result = self.client.send_text(PHONE, "Olá")

        self.assertEqual(result, {"key": {"id": "MSG1"}})

    def test_human_agent_is_accepted_and_ignored(self):
        """WhatsApp has no messaging window; the kwarg must not alter the payload."""
        self.client.send_text(PHONE, "Olá", human_agent=True)

        self.assertEqual(self.post.call_args.kwargs["json"], {"number": PHONE, "text": "Olá"})

    def test_successful_send_is_logged_as_sent(self):
        self.client.send_text(PHONE, "Olá", source="handover", contact_id=7)

        self.log_outbound.assert_called_once()
        args, kwargs = self.log_outbound.call_args
        self.assertEqual(args, (PHONE, "Olá"))
        self.assertEqual(kwargs["delivery"], "sent")
        self.assertEqual(kwargs["source"], "handover")
        self.assertEqual(kwargs["contact_id"], 7)


class TestSimulation(unittest.TestCase):
    def setUp(self):
        post_patch = patch("whatbot.channels.whatsapp_evolution.requests.post")
        log_patch = patch("whatbot.channels.whatsapp_evolution.log_outbound")
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
        log_patch = patch("whatbot.channels.whatsapp_evolution.log_outbound")
        self.log_outbound = log_patch.start()
        self.addCleanup(log_patch.stop)

    def test_transport_failure_is_logged_as_failed(self):
        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post",
            side_effect=requests.ConnectionError("sem rede"),
        ):
            with self.assertRaises(Exception):
                build_client().send_text(PHONE, "Olá")

        kwargs = self.log_outbound.call_args.kwargs
        self.assertEqual(kwargs["delivery"], "failed")
        self.assertIn("sem rede", kwargs["error"])

    def test_http_error_response_raises(self):
        response = MagicMock(ok=False, status_code=401, text="unauthorized")
        response.raise_for_status.side_effect = requests.HTTPError("401")

        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post", return_value=response
        ):
            with self.assertRaises(Exception):
                build_client().send_text(PHONE, "Olá")

        self.assertEqual(self.log_outbound.call_args.kwargs["delivery"], "failed")


if __name__ == "__main__":
    unittest.main()
