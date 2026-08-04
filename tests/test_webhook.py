import unittest

from whatbot.webhook import _extract_order, _extract_text, parse_evolution_payload


def _order_payload(order_message: dict, phone: str = "5511999999999") -> dict:
    return {
        "event": "messages.upsert",
        "instance": "bot_whatsapp",
        "data": {
            "key": {
                "remoteJid": f"{phone}@s.whatsapp.net",
                "fromMe": False,
                "id": "ORDER123",
            },
            "pushName": "Cliente",
            "message": {"orderMessage": order_message},
        },
    }


class TestEvolutionWebhookParser(unittest.TestCase):
    def test_parse_conversation_message(self):
        payload = {
            "event": "messages.upsert",
            "instance": "bot_whatsapp",
            "data": {
                "key": {
                    "remoteJid": "5511999999999@s.whatsapp.net",
                    "fromMe": False,
                    "id": "ABC123",
                },
                "pushName": "Cliente",
                "message": {"conversation": "Olá, quero saber sobre yoga"},
            },
        }

        parsed = parse_evolution_payload(payload)

        self.assertEqual(parsed["from_number"], "5511999999999")
        self.assertEqual(parsed["text"], "Olá, quero saber sobre yoga")
        self.assertEqual(parsed["push_name"], "Cliente")
        self.assertIsNone(parsed["order"])

    def test_ignore_outgoing_messages(self):
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "5511999999999@s.whatsapp.net",
                    "fromMe": True,
                },
                "message": {"conversation": "Resposta do bot"},
            },
        }

        self.assertIsNone(parse_evolution_payload(payload))

    def test_ignore_group_messages(self):
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "120363000000000000@g.us",
                    "fromMe": False,
                },
                "message": {"conversation": "Mensagem de grupo"},
            },
        }

        self.assertIsNone(parse_evolution_payload(payload))


class TestExtractOrder(unittest.TestCase):
    """`whatbot/webhook.py::_extract_order` — captura de pedidos do catálogo
    (openspec/changes/catalog-order-capture)."""

    def _android_order_message(self) -> dict:
        return {
            "orderId": "ORD-42",
            "itemCount": 2,
            "orderTitle": "Pedido de camisetas",
            "items": [
                {"productId": "PROD-1", "quantity": 1},
                {"productId": "PROD-2", "quantity": 3},
            ],
        }

    def _ios_order_message(self) -> dict:
        # iOS orders arrive without productId/retailerId on any item and
        # with orderTitle set to the Evolution instance name, not the
        # order's actual title (evolution-foundation/evolution-api#1819).
        return {
            "orderId": "ORD-43",
            "itemCount": 3,
            "orderTitle": "whatbot",
            "items": [],
        }

    def test_no_order_message_returns_none(self):
        self.assertIsNone(_extract_order({"conversation": "oi"}))
        self.assertIsNone(_extract_order({}))

    def test_android_order_is_fully_identifiable(self):
        order = _extract_order({"orderMessage": self._android_order_message()})

        self.assertIsNotNone(order)
        self.assertEqual(order["order_id"], "ORD-42")
        self.assertEqual(order["item_count"], 2)
        self.assertEqual(order["order_title"], "Pedido de camisetas")
        self.assertEqual(len(order["items"]), 2)
        self.assertTrue(order["items_identifiable"])

    def test_ios_order_without_items_is_not_identifiable(self):
        order = _extract_order({"orderMessage": self._ios_order_message()})

        self.assertIsNotNone(order)
        self.assertEqual(order["order_id"], "ORD-43")
        self.assertEqual(order["item_count"], 3)
        self.assertEqual(order["items"], [])
        self.assertFalse(order["items_identifiable"])

    def test_order_with_partial_product_ids_is_not_identifiable(self):
        order_message = {
            "orderId": "ORD-44",
            "itemCount": 2,
            "items": [{"productId": "PROD-1"}, {"quantity": 1}],
        }

        order = _extract_order({"orderMessage": order_message})

        self.assertFalse(order["items_identifiable"])

    def test_empty_order_message_dict_is_still_recognized_as_an_order(self):
        """`{"orderMessage": {}}` is falsy but still means "this is an
        order, just with no data" — must not be treated the same as "no
        orderMessage at all" (that would fall the message back into the
        original silent-drop bug this change fixes)."""
        order = _extract_order({"orderMessage": {}})

        self.assertIsNotNone(order)
        self.assertEqual(order["items"], [])
        self.assertFalse(order["items_identifiable"])


class TestExtractTextCatalogOrder(unittest.TestCase):
    """`_extract_text` never returns empty for an `orderMessage`."""

    def test_identifiable_order_produces_synthetic_text_with_item_count(self):
        message = {
            "orderMessage": {
                "orderId": "ORD-1",
                "itemCount": 2,
                "items": [{"productId": "P1"}, {"productId": "P2"}],
            }
        }

        self.assertEqual(_extract_text(message), "[pedido do catálogo] 2 item(ns)")

    def test_unidentifiable_order_produces_synthetic_text_saying_so(self):
        message = {
            "orderMessage": {
                "orderId": "ORD-2",
                "itemCount": 1,
                "items": [],
            }
        }

        self.assertEqual(
            _extract_text(message), "[pedido do catálogo] itens não identificados"
        )

    def test_empty_order_message_dict_still_produces_synthetic_text(self):
        self.assertEqual(
            _extract_text({"orderMessage": {}}),
            "[pedido do catálogo] itens não identificados",
        )


class TestExtractTextRegressionOtherMessageTypes(unittest.TestCase):
    """No regression on message types already handled before this change."""

    def test_conversation(self):
        self.assertEqual(
            _extract_text({"conversation": "oi tudo bem"}), "oi tudo bem"
        )

    def test_extended_text_message(self):
        self.assertEqual(
            _extract_text({"extendedTextMessage": {"text": "olá"}}), "olá"
        )

    def test_image_message_caption(self):
        self.assertEqual(
            _extract_text({"imageMessage": {"caption": "confira"}}), "confira"
        )

    def test_video_message_caption(self):
        self.assertEqual(
            _extract_text({"videoMessage": {"caption": "veja isso"}}), "veja isso"
        )

    def test_buttons_response_message(self):
        self.assertEqual(
            _extract_text(
                {"buttonsResponseMessage": {"selectedDisplayText": "Sim"}}
            ),
            "Sim",
        )

    def test_list_response_message(self):
        self.assertEqual(
            _extract_text(
                {
                    "listResponseMessage": {
                        "title": "Yoga",
                        "description": "Turma da manhã",
                    }
                }
            ),
            "Yoga Turma da manhã",
        )

    def test_unknown_message_type_still_returns_empty(self):
        self.assertEqual(_extract_text({"unknownMessageType": {}}), "")


class TestParseEvolutionPayloadCatalogOrder(unittest.TestCase):
    """`parse_evolution_payload` attaches `order` without being dropped by
    the `if not text: return None` guard (Requirement "Pedido do catálogo
    nunca é descartado")."""

    def test_android_order_is_never_dropped_and_carries_items(self):
        order_message = {
            "orderId": "ORD-42",
            "itemCount": 2,
            "orderTitle": "Pedido de camisetas",
            "items": [
                {"productId": "PROD-1", "quantity": 1},
                {"productId": "PROD-2", "quantity": 3},
            ],
        }

        parsed = parse_evolution_payload(_order_payload(order_message))

        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["text"])
        self.assertIsNotNone(parsed["order"])
        self.assertTrue(parsed["order"]["items_identifiable"])
        self.assertEqual(len(parsed["order"]["items"]), 2)

    def test_ios_order_without_items_is_still_captured_not_dropped(self):
        order_message = {
            "orderId": "ORD-43",
            "itemCount": 3,
            "orderTitle": "whatbot",
            "items": [],
        }

        parsed = parse_evolution_payload(_order_payload(order_message))

        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["text"])
        self.assertIsNotNone(parsed["order"])
        self.assertFalse(parsed["order"]["items_identifiable"])
        self.assertIn("não identificados", parsed["text"])

    def test_regular_message_has_order_none(self):
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "5511999999999@s.whatsapp.net",
                    "fromMe": False,
                    "id": "MSG1",
                },
                "message": {"conversation": "Qual o horário?"},
            },
        }

        parsed = parse_evolution_payload(payload)

        self.assertIsNotNone(parsed)
        self.assertIsNone(parsed["order"])

    def test_empty_order_message_dict_is_never_dropped(self):
        parsed = parse_evolution_payload(_order_payload({}))

        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["text"])
        self.assertIsNotNone(parsed["order"])


if __name__ == "__main__":
    unittest.main()
