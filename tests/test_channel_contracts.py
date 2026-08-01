"""Regression tests for the channel-layer defects found auditing Fase 1.

Each test here pins one fix. If the corresponding fix is reverted, the test
must fail — that is the point of the file.
"""

import unittest

import requests

from whatbot.channels import (
    INSTAGRAM,
    SUPPORTED_CHANNELS,
    WHATSAPP,
    ChannelError,
    ChannelRouter,
    InboundMessage,
    UnknownChannelError,
    normalize_channel,
    send_admin,
    send_to_contact,
    validate_channel,
)
from whatbot.channels.whatsapp_evolution import EvolutionApiClient
from whatbot.webhook import parse_evolution_payload

from fakes import DuckRouter, FakeClient

PHONE = "5511999999999"
IGSID = "17841400000000000"


class TestChannelValidation(unittest.TestCase):
    """D2 — an unsupported channel must be rejected where it arrives."""

    def test_supported_channels_pass_through(self):
        for canal in SUPPORTED_CHANNELS:
            self.assertEqual(validate_channel(canal), canal)

    def test_absent_channel_still_defaults(self):
        self.assertEqual(validate_channel(None), WHATSAPP)
        self.assertEqual(validate_channel("   "), WHATSAPP)

    def test_case_and_padding_are_tolerated(self):
        self.assertEqual(validate_channel("  Instagram "), INSTAGRAM)

    def test_unsupported_channel_is_rejected_by_name(self):
        with self.assertRaises(UnknownChannelError) as ctx:
            validate_channel("telegram")
        self.assertIn("telegram", str(ctx.exception))

    def test_normalize_stays_lenient(self):
        """The router's own error path relies on normalization not raising."""
        self.assertEqual(normalize_channel("telegram"), "telegram")


class TestDispatchByCapability(unittest.TestCase):
    """D5 — helpers must detect a router by capability, not concrete type."""

    def setUp(self):
        self.wa = FakeClient(WHATSAPP)
        self.ig = FakeClient(INSTAGRAM)
        self.duck = DuckRouter([self.wa, self.ig])

    def test_duck_router_keeps_the_channel(self):
        send_to_contact(self.duck, IGSID, "oi", canal=INSTAGRAM)

        self.assertEqual(len(self.ig.sent), 1)
        self.assertEqual(self.wa.sent, [])

    def test_duck_router_keeps_human_agent(self):
        send_to_contact(self.duck, IGSID, "oi", canal=INSTAGRAM, human_agent=True)

        self.assertTrue(self.ig.sent[0]["human_agent"])

    def test_duck_router_still_pins_admin_to_the_admin_channel(self):
        send_admin(self.duck, PHONE, "resumo")

        self.assertEqual(len(self.wa.sent), 1)
        self.assertEqual(self.ig.sent, [])


class TestInboundMessageNormalization(unittest.TestCase):
    """D6 — the entry format must be built once and be case-insensitive."""

    def test_channel_case_does_not_change_the_payload_shape(self):
        payload = InboundMessage(
            canal="WhatsApp", external_id=PHONE, text="oi"
        ).to_payload()

        self.assertEqual(payload["canal"], WHATSAPP)
        self.assertEqual(payload["from_number"], PHONE)

    def test_parser_emits_the_inbound_message_shape(self):
        parsed = parse_evolution_payload(
            {
                "event": "messages.upsert",
                "instance": "whatbot",
                "data": {
                    "key": {
                        "remoteJid": f"{PHONE}@s.whatsapp.net",
                        "fromMe": False,
                        "id": "ABC",
                    },
                    "pushName": "Cliente",
                    "message": {"conversation": "Olá"},
                },
            }
        )

        self.assertEqual(parsed["canal"], WHATSAPP)
        self.assertEqual(parsed["external_id"], PHONE)
        self.assertEqual(parsed["from_number"], PHONE)
        self.assertEqual(parsed["message_id"], "ABC")
        self.assertEqual(parsed["instance"], "whatbot")


class TestClientProtocolAlignment(unittest.TestCase):
    """D3/D4 — the client must match the protocol and fail with a typed error."""

    def setUp(self):
        self.client = EvolutionApiClient(
            api_key="k", instance_name="whatbot", base_url="http://evo:8080"
        )

    def test_recipient_can_be_passed_by_keyword(self):
        from unittest.mock import MagicMock, patch

        response = MagicMock(ok=True)
        response.json.return_value = {}
        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post", return_value=response
        ), patch("whatbot.channels.whatsapp_evolution.log_outbound"):
            self.client.send_text(to=PHONE, text="oi")

    def test_router_accepts_any_protocol_client(self):
        router = ChannelRouter([self.client])
        self.assertIs(router.client_for(WHATSAPP), self.client)

    def test_connection_failure_is_a_retryable_channel_error(self):
        from unittest.mock import patch

        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post",
            side_effect=requests.ConnectionError("sem rede"),
        ), patch("whatbot.channels.whatsapp_evolution.log_outbound"):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(PHONE, "oi")

        self.assertEqual(ctx.exception.canal, WHATSAPP)
        self.assertTrue(ctx.exception.retryable)

    def test_http_rejection_is_not_retryable(self):
        from unittest.mock import MagicMock, patch

        response = MagicMock(ok=False, status_code=401, text="unauthorized")
        response.raise_for_status.side_effect = requests.HTTPError("401")
        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post", return_value=response
        ), patch("whatbot.channels.whatsapp_evolution.log_outbound"):
            with self.assertRaises(ChannelError) as ctx:
                self.client.send_text(PHONE, "oi")

        self.assertFalse(ctx.exception.retryable)


if __name__ == "__main__":
    unittest.main()
