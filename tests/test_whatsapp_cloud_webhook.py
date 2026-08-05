"""Tests for the WhatsApp Cloud API webhook parser
(`whatbot/whatsapp_cloud_webhook.py`).

Covers each edge case listed in the "Parser reconhece formato de mensagem da
Cloud API" requirement: plain text, media-only message, delivery/read status
events (must never produce an InboundMessage), and multiple
events/entries/changes in a single POST. No network involved — this module
is pure parsing.
"""

import unittest

from whatbot.channels import WHATSAPP
from whatbot.whatsapp_cloud_webhook import (
    KIND_MALFORMED,
    KIND_MEDIA_ONLY,
    KIND_MESSAGE,
    KIND_STATUS,
    classify_whatsapp_cloud_event,
    parse_whatsapp_cloud_media_message,
    parse_whatsapp_cloud_message,
    parse_whatsapp_cloud_payload,
)

PHONE = "16315551234"
PHONE_NUMBER_ID = "1234567890"
WABA_ID = "9876543210"


def _event(**overrides):
    base = {
        "from": PHONE,
        "id": "wamid.HBgMMTYzMTU1NTEyMzQVAgASGBQzQTQzOTU=",
        "timestamp": "1753700000",
        "type": "text",
        "text": {"body": "oi, tem yoga?"},
    }
    base.update(overrides)
    return base


def _value(*, messages=None, statuses=None, contacts=None):
    value = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "15550001111",
            "phone_number_id": PHONE_NUMBER_ID,
        },
    }
    if contacts is not None:
        value["contacts"] = contacts
    if messages is not None:
        value["messages"] = messages
    if statuses is not None:
        value["statuses"] = statuses
    return value


def _wrap(*values):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA_ID,
                "changes": [{"value": value, "field": "messages"} for value in values],
            }
        ],
    }


class TestClassifyEvent(unittest.TestCase):
    def test_plain_text_message_is_classified_as_message(self):
        self.assertEqual(classify_whatsapp_cloud_event(_event()), KIND_MESSAGE)

    def test_media_only_message_has_no_text(self):
        event = _event(
            type="image",
            image={"id": "MEDIA_ID", "mime_type": "image/jpeg"},
        )
        del event["text"]
        self.assertEqual(classify_whatsapp_cloud_event(event), KIND_MEDIA_ONLY)

    def test_malformed_event_without_from(self):
        event = _event()
        del event["from"]
        self.assertEqual(classify_whatsapp_cloud_event(event), KIND_MALFORMED)

    def test_malformed_event_without_id(self):
        event = _event()
        del event["id"]
        self.assertEqual(classify_whatsapp_cloud_event(event), KIND_MALFORMED)

    def test_non_dict_event(self):
        self.assertEqual(classify_whatsapp_cloud_event("not-a-dict"), KIND_MALFORMED)


class TestParseWhatsAppCloudMessage(unittest.TestCase):
    def test_parses_plain_text_into_inbound_message_shape(self):
        value = _value(
            messages=[_event()],
            contacts=[{"profile": {"name": "Kerry"}, "wa_id": PHONE}],
        )
        parsed = parse_whatsapp_cloud_message(value, _event())

        self.assertEqual(parsed["canal"], WHATSAPP)
        self.assertEqual(parsed["external_id"], PHONE)
        self.assertEqual(parsed["from_number"], PHONE)
        self.assertEqual(parsed["text"], "oi, tem yoga?")
        self.assertEqual(parsed["push_name"], "Kerry")
        self.assertEqual(parsed["message_id"], _event()["id"])

    def test_no_matching_contact_leaves_display_name_none(self):
        value = _value(messages=[_event()])
        parsed = parse_whatsapp_cloud_message(value, _event())

        self.assertIsNone(parsed["push_name"])

    def test_media_only_is_not_a_message(self):
        event = _event(type="image", image={"id": "MEDIA_ID"})
        del event["text"]
        self.assertIsNone(parse_whatsapp_cloud_message(_value(), event))


class TestParseWhatsAppCloudMediaMessage(unittest.TestCase):
    """`parse_whatsapp_cloud_media_message` (conversation-history-media-storage):
    antes, um evento `KIND_MEDIA_ONLY` não produzia nenhum `data` (mídia
    inteiramente descartada) — agora produz o mesmo formato normalizado de
    `parse_whatsapp_cloud_message`, com `media` no lugar de texto."""

    def _media_event(self, tipo: str, **media_overrides):
        media_obj = {"id": "MEDIA_ID", "mime_type": f"{tipo}/x"}
        media_obj.update(media_overrides)
        event = _event(type=tipo, **{tipo: media_obj})
        del event["text"]
        return event

    def test_not_a_media_event_returns_none(self):
        self.assertIsNone(parse_whatsapp_cloud_media_message(_value(), _event()))

    def test_image_message_produces_media_reference(self):
        event = self._media_event("image", caption="olha isso")
        parsed = parse_whatsapp_cloud_media_message(_value(), event)

        self.assertEqual(parsed["canal"], WHATSAPP)
        self.assertEqual(parsed["external_id"], PHONE)
        self.assertEqual(parsed["text"], "")
        self.assertEqual(parsed["message_id"], event["id"])
        self.assertEqual(
            parsed["media"],
            {
                "tipo": "image",
                "provider_media_id": "MEDIA_ID",
                "mime_type": "image/x",
                "caption": "olha isso",
            },
        )

    def test_audio_video_document_sticker_all_produce_media_reference(self):
        for tipo in ("audio", "video", "document", "sticker"):
            with self.subTest(tipo=tipo):
                event = self._media_event(tipo)
                parsed = parse_whatsapp_cloud_media_message(_value(), event)
                self.assertEqual(parsed["media"]["tipo"], tipo)
                self.assertEqual(parsed["media"]["provider_media_id"], "MEDIA_ID")

    def test_media_object_without_id_is_not_a_media_message(self):
        event = _event(type="image", image={"mime_type": "image/jpeg"})
        del event["text"]
        self.assertIsNone(parse_whatsapp_cloud_media_message(_value(), event))


class TestParseWhatsAppCloudPayload(unittest.TestCase):
    def test_wrong_object_type_returns_no_events(self):
        payload = {"object": "page", "entry": []}
        self.assertEqual(parse_whatsapp_cloud_payload(payload), [])

    def test_single_text_message(self):
        payload = _wrap(_value(messages=[_event()]))
        results = parse_whatsapp_cloud_payload(payload)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["kind"], KIND_MESSAGE)
        self.assertEqual(results[0]["data"]["external_id"], PHONE)

    def test_status_event_produces_no_inbound_message(self):
        payload = _wrap(
            _value(
                statuses=[
                    {
                        "id": "wamid.XYZ",
                        "status": "delivered",
                        "timestamp": "1753700001",
                        "recipient_id": PHONE,
                    }
                ]
            )
        )
        results = parse_whatsapp_cloud_payload(payload)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["kind"], KIND_STATUS)
        self.assertIsNone(results[0]["data"])

    def test_multiple_messages_in_one_change_are_all_processed(self):
        media_event = _event(id="wamid.2", type="image", image={"id": "MEDIA_ID"})
        del media_event["text"]
        payload = _wrap(_value(messages=[_event(), media_event]))

        results = parse_whatsapp_cloud_payload(payload)

        self.assertEqual(len(results), 2)
        self.assertEqual([r["kind"] for r in results], [KIND_MESSAGE, KIND_MEDIA_ONLY])
        # conversation-history-media-storage: o evento de mídia agora carrega
        # `data` (referência de mídia), não mais `None`.
        self.assertIsNotNone(results[1]["data"])
        self.assertEqual(results[1]["data"]["media"]["provider_media_id"], "MEDIA_ID")

    def test_multiple_changes_and_entries_are_all_processed(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": WABA_ID,
                    "changes": [
                        {"value": _value(messages=[_event()]), "field": "messages"}
                    ],
                },
                {
                    "id": WABA_ID,
                    "changes": [
                        {
                            "value": _value(
                                messages=[_event(id="wamid.2", text={"body": "segunda"})]
                            ),
                            "field": "messages",
                        }
                    ],
                },
            ],
        }

        results = parse_whatsapp_cloud_payload(payload)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["kind"] == KIND_MESSAGE for r in results))

    def test_message_and_status_in_the_same_post_are_both_processed(self):
        payload = _wrap(
            _value(
                messages=[_event()],
                statuses=[
                    {"id": "wamid.OLD", "status": "read", "timestamp": "1753699999"}
                ],
            )
        )
        results = parse_whatsapp_cloud_payload(payload)

        self.assertEqual([r["kind"] for r in results], [KIND_STATUS, KIND_MESSAGE])

    def test_malformed_event_does_not_raise(self):
        payload = _wrap(_value(messages=[{"weird": "shape"}]))
        results = parse_whatsapp_cloud_payload(payload)

        self.assertEqual(results[0]["kind"], KIND_MALFORMED)
        self.assertIsNone(results[0]["data"])

    def test_non_dict_payload_returns_no_events(self):
        self.assertEqual(parse_whatsapp_cloud_payload(None), [])
        self.assertEqual(parse_whatsapp_cloud_payload("oops"), [])

    def test_change_without_messages_or_statuses_is_ignored_without_error(self):
        payload = _wrap(_value())
        self.assertEqual(parse_whatsapp_cloud_payload(payload), [])


if __name__ == "__main__":
    unittest.main()
