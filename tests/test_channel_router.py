import unittest

from whatbot.channels import (
    DEFAULT_CHANNEL,
    INSTAGRAM,
    WHATSAPP,
    ChannelRouter,
    InboundMessage,
    UnknownChannelError,
    channel_label,
    normalize_channel,
    send_admin,
    send_to_contact,
)

from fakes import FakeClient, LegacyClient


class TestChannelNames(unittest.TestCase):
    def test_normalize_defaults_to_whatsapp(self):
        self.assertEqual(normalize_channel(None), WHATSAPP)
        self.assertEqual(normalize_channel(""), WHATSAPP)
        self.assertEqual(normalize_channel("  "), WHATSAPP)
        self.assertEqual(DEFAULT_CHANNEL, WHATSAPP)

    def test_normalize_is_case_insensitive(self):
        self.assertEqual(normalize_channel("Instagram"), INSTAGRAM)
        self.assertEqual(normalize_channel(" WHATSAPP "), WHATSAPP)

    def test_labels(self):
        self.assertEqual(channel_label(INSTAGRAM), "Instagram")
        self.assertEqual(channel_label(None), "WhatsApp")


class TestChannelRouter(unittest.TestCase):
    def setUp(self):
        self.wa = FakeClient(WHATSAPP)
        self.ig = FakeClient(INSTAGRAM)
        self.router = ChannelRouter([self.wa, self.ig])

    def test_registers_channels(self):
        self.assertEqual(self.router.channels, [INSTAGRAM, WHATSAPP])
        self.assertTrue(self.router.has(INSTAGRAM))
        self.assertFalse(self.router.has("telegram"))

    def test_resolves_client_by_channel(self):
        self.assertIs(self.router.client_for(WHATSAPP), self.wa)
        self.assertIs(self.router.client_for(INSTAGRAM), self.ig)

    def test_unspecified_channel_falls_back_to_default(self):
        self.assertIs(self.router.client_for(None), self.wa)
        self.router.send_text("5511999999999", "oi")
        self.assertEqual(len(self.wa.sent), 1)
        self.assertEqual(len(self.ig.sent), 0)

    def test_routes_to_instagram(self):
        self.router.send_text("17841400000000000", "oi", canal=INSTAGRAM)
        self.assertEqual(len(self.ig.sent), 1)
        self.assertEqual(len(self.wa.sent), 0)

    def test_unknown_channel_fails_explicitly(self):
        with self.assertRaises(UnknownChannelError) as ctx:
            self.router.send_text("123", "oi", canal="telegram")
        self.assertIn("telegram", str(ctx.exception))

    def test_forwards_all_kwargs(self):
        self.router.send_text(
            "17841400000000000",
            "oi",
            canal=INSTAGRAM,
            source="handover",
            contact_id=7,
            simulated=True,
            human_agent=True,
        )
        sent = self.ig.sent[0]
        self.assertEqual(sent["source"], "handover")
        self.assertEqual(sent["contact_id"], 7)
        self.assertTrue(sent["simulated"])
        self.assertTrue(sent["human_agent"])

    def test_admin_always_uses_admin_channel(self):
        """Even with an Instagram customer in play, admins are reached on WhatsApp."""
        self.router.send_admin_text("5511949305094", "fila cheia")
        self.assertEqual(len(self.wa.sent), 1)
        self.assertEqual(len(self.ig.sent), 0)
        self.assertEqual(self.wa.sent[0]["source"], "admin")

    def test_missing_admin_channel_is_explicit(self):
        ig_only = ChannelRouter([FakeClient(INSTAGRAM)])
        with self.assertRaises(UnknownChannelError):
            ig_only.send_admin_text("5511949305094", "fila cheia")


class TestDispatchHelpers(unittest.TestCase):
    """The helpers must accept both a router and a bare client."""

    def test_send_to_contact_with_router(self):
        ig = FakeClient(INSTAGRAM)
        router = ChannelRouter([FakeClient(WHATSAPP), ig])
        send_to_contact(router, "178414", "oi", canal=INSTAGRAM, human_agent=True)
        self.assertTrue(ig.sent[0]["human_agent"])

    def test_send_to_contact_with_legacy_client_drops_channel_kwargs(self):
        legacy = LegacyClient()
        send_to_contact(legacy, "5511999999999", "oi", canal=INSTAGRAM, human_agent=True)
        self.assertEqual(legacy.sent, [("5511999999999", "oi", "bot")])

    def test_send_admin_with_router(self):
        wa = FakeClient(WHATSAPP)
        router = ChannelRouter([wa, FakeClient(INSTAGRAM)])
        send_admin(router, "5511949305094", "resumo")
        self.assertEqual(wa.sent[0]["source"], "admin")

    def test_send_admin_with_bare_client(self):
        legacy = LegacyClient()
        send_admin(legacy, "5511949305094", "resumo", source="admin_notify")
        self.assertEqual(legacy.sent, [("5511949305094", "resumo", "admin_notify")])


class TestInboundMessage(unittest.TestCase):
    def test_whatsapp_payload_keeps_legacy_shape(self):
        msg = InboundMessage(
            canal=WHATSAPP,
            external_id="5511999999999",
            text="olá",
            display_name="Cliente",
            message_id="ABC",
        )
        payload = msg.to_payload()
        self.assertEqual(payload["from_number"], "5511999999999")
        self.assertEqual(payload["canal"], WHATSAPP)
        self.assertEqual(payload["push_name"], "Cliente")

    def test_instagram_payload_has_no_phone_field(self):
        msg = InboundMessage(
            canal=INSTAGRAM, external_id="17841400000000000", text="oi"
        )
        payload = msg.to_payload()
        self.assertNotIn("from_number", payload)
        self.assertEqual(payload["external_id"], "17841400000000000")

    def test_echo_defaults_to_false(self):
        msg = InboundMessage(canal=WHATSAPP, external_id="55119", text="x")
        self.assertFalse(msg.is_echo)


if __name__ == "__main__":
    unittest.main()
