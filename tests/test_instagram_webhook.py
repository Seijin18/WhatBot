"""Tests for the Instagram webhook parser (`whatbot/instagram_webhook.py`).

Covers each edge case listed in the "Parser reconhece formatos e casos de
borda do Instagram" requirement: plain text, echo, story mention/reply,
media-only message, deleted-message notification and multiple events in a
single POST. No network involved — this module is pure parsing.
"""

import unittest

from whatbot.channels import INSTAGRAM
from whatbot.instagram_webhook import (
    KIND_DELETED,
    KIND_ECHO,
    KIND_MALFORMED,
    KIND_MEDIA_ONLY,
    KIND_MESSAGE,
    KIND_STORY,
    classify_instagram_event,
    parse_instagram_echo,
    parse_instagram_message,
    parse_instagram_payload,
)

IGSID = "17841400000000001"
PAGE_ID = "17841400000000000"


def _event(**overrides):
    base = {
        "sender": {"id": IGSID},
        "recipient": {"id": PAGE_ID},
        "timestamp": 1753700000,
        "message": {"mid": "aWc123", "text": "oi, tem yoga?"},
    }
    base.update(overrides)
    return base


def _wrap(*events, account_id=PAGE_ID):
    return {
        "object": "instagram",
        "entry": [{"id": account_id, "time": 1753700000, "messaging": list(events)}],
    }


class TestClassifyEvent(unittest.TestCase):
    def test_plain_text_message_is_classified_as_message(self):
        self.assertEqual(classify_instagram_event(_event()), KIND_MESSAGE)

    def test_echo_from_own_account(self):
        event = _event(
            sender={"id": PAGE_ID},
            recipient={"id": IGSID},
            message={"mid": "aWc999", "text": "Já te respondo!", "is_echo": True},
        )
        self.assertEqual(classify_instagram_event(event), KIND_ECHO)

    def test_media_only_message_has_no_text(self):
        event = _event(message={"mid": "aWc1", "attachments": [{"type": "image"}]})
        self.assertEqual(classify_instagram_event(event), KIND_MEDIA_ONLY)

    def test_story_mention(self):
        event = _event(
            message={
                "mid": "aWc2",
                "attachments": [{"type": "story_mention", "payload": {"url": "x"}}],
            }
        )
        self.assertEqual(classify_instagram_event(event), KIND_STORY)

    def test_reply_to_story(self):
        event = _event(
            message={
                "mid": "aWc3",
                "text": "adorei!",
                "reply_to": {"story": {"url": "x", "id": "123"}},
            }
        )
        self.assertEqual(classify_instagram_event(event), KIND_STORY)

    def test_deleted_message_notification(self):
        event = _event(message={"mid": "aWc4", "is_deleted": True})
        self.assertEqual(classify_instagram_event(event), KIND_DELETED)

    def test_malformed_event_without_message(self):
        self.assertEqual(classify_instagram_event({"sender": {"id": IGSID}}), KIND_MALFORMED)

    def test_malformed_event_without_sender(self):
        event = {"message": {"mid": "aWc5", "text": "oi"}}
        self.assertEqual(classify_instagram_event(event), KIND_MALFORMED)

    def test_non_dict_event(self):
        self.assertEqual(classify_instagram_event("not-a-dict"), KIND_MALFORMED)


class TestParseInstagramMessage(unittest.TestCase):
    def test_parses_plain_text_into_inbound_message_shape(self):
        parsed = parse_instagram_message(_event())

        self.assertEqual(parsed["canal"], INSTAGRAM)
        self.assertEqual(parsed["external_id"], IGSID)
        self.assertEqual(parsed["text"], "oi, tem yoga?")
        self.assertEqual(parsed["message_id"], "aWc123")

    def test_echo_event_is_not_a_message(self):
        event = _event(
            sender={"id": PAGE_ID},
            message={"mid": "aWc9", "text": "oi", "is_echo": True},
        )
        self.assertIsNone(parse_instagram_message(event))

    def test_media_only_is_not_a_message(self):
        event = _event(message={"mid": "aWc1", "attachments": [{"type": "image"}]})
        self.assertIsNone(parse_instagram_message(event))

    def test_deleted_is_not_a_message(self):
        event = _event(message={"mid": "aWc4", "is_deleted": True})
        self.assertIsNone(parse_instagram_message(event))


class TestParseInstagramEcho(unittest.TestCase):
    def test_parses_echo_as_outbound_from_the_secretariat(self):
        event = _event(
            sender={"id": PAGE_ID},
            recipient={"id": IGSID},
            message={"mid": "aWc9", "text": "Já te respondo!", "is_echo": True},
        )
        parsed = parse_instagram_echo(event)

        self.assertEqual(parsed["canal"], INSTAGRAM)
        self.assertEqual(parsed["to_number"], IGSID)
        self.assertEqual(parsed["text"], "Já te respondo!")
        self.assertTrue(parsed["from_me"])

    def test_echo_without_text_gets_a_placeholder(self):
        event = _event(
            sender={"id": PAGE_ID},
            recipient={"id": IGSID},
            message={"mid": "aWc9", "attachments": [{"type": "image"}], "is_echo": True},
        )
        parsed = parse_instagram_echo(event)

        self.assertEqual(parsed["text"], "[mensagem]")

    def test_plain_message_is_not_an_echo(self):
        self.assertIsNone(parse_instagram_echo(_event()))


class TestParseInstagramPayload(unittest.TestCase):
    def test_wrong_object_type_returns_no_events(self):
        payload = {"object": "page", "entry": []}
        self.assertEqual(parse_instagram_payload(payload), [])

    def test_single_text_message(self):
        payload = _wrap(_event())
        results = parse_instagram_payload(payload)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["kind"], KIND_MESSAGE)
        self.assertEqual(results[0]["data"]["external_id"], IGSID)

    def test_multiple_events_in_a_single_post_are_all_processed(self):
        echo_event = _event(
            sender={"id": PAGE_ID},
            recipient={"id": IGSID},
            message={"mid": "aWc9", "text": "Já te respondo!", "is_echo": True},
        )
        media_event = _event(message={"mid": "aWc1", "attachments": [{"type": "image"}]})
        payload = _wrap(_event(), echo_event, media_event)

        results = parse_instagram_payload(payload)

        self.assertEqual(len(results), 3)
        self.assertEqual([r["kind"] for r in results], [KIND_MESSAGE, KIND_ECHO, KIND_MEDIA_ONLY])

    def test_multiple_entries_are_all_processed(self):
        payload = {
            "object": "instagram",
            "entry": [
                {"id": PAGE_ID, "time": 1, "messaging": [_event()]},
                {
                    "id": PAGE_ID,
                    "time": 2,
                    "messaging": [_event(message={"mid": "aWc2", "text": "segunda"})],
                },
            ],
        }

        results = parse_instagram_payload(payload)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["kind"] == KIND_MESSAGE for r in results))

    def test_deleted_message_is_distinguished_from_a_new_message(self):
        payload = _wrap(_event(message={"mid": "aWc4", "is_deleted": True}))
        results = parse_instagram_payload(payload)

        self.assertEqual(results[0]["kind"], KIND_DELETED)
        self.assertIsNone(results[0]["data"])

    def test_story_mention_does_not_raise_and_is_classified(self):
        payload = _wrap(
            _event(
                message={
                    "mid": "aWc2",
                    "attachments": [{"type": "story_mention"}],
                }
            )
        )
        results = parse_instagram_payload(payload)

        self.assertEqual(results[0]["kind"], KIND_STORY)
        self.assertIsNone(results[0]["data"])

    def test_malformed_event_does_not_raise(self):
        payload = _wrap({"weird": "shape"})
        results = parse_instagram_payload(payload)

        self.assertEqual(results[0]["kind"], KIND_MALFORMED)
        self.assertIsNone(results[0]["data"])

    def test_non_dict_payload_returns_no_events(self):
        self.assertEqual(parse_instagram_payload(None), [])
        self.assertEqual(parse_instagram_payload("oops"), [])

    def test_entry_without_messaging_key_is_ignored_without_error(self):
        payload = {"object": "instagram", "entry": [{"id": PAGE_ID, "time": 1}]}
        self.assertEqual(parse_instagram_payload(payload), [])


if __name__ == "__main__":
    unittest.main()
