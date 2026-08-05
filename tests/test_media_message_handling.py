"""End-to-end tests for inbound media handling (`whatbot/main.py::_handle_media_message`).

Enters through `main_mod.main(payload)`, same seam as `test_main_e2e.py`,
with a media-only payload shaped like `parse_whatsapp_cloud_media_message`
produces it (`whatbot/whatsapp_cloud_webhook.py`).
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from whatbot import main as main_mod
from whatbot.channels import WHATSAPP, ChannelError, ChannelRouter
from whatbot.storage import factory as storage_factory

from fakes import FakeClient, FakeDatabase, FakeLlm

ADMIN_PHONE = "5511900000001"
CUSTOMER_PHONE = "5511999999999"

BASE_ENV = {
    "ADMIN_NOTIFY_PHONES": ADMIN_PHONE,
    "TEST_MODE": "false",
    "GEMINI_API_KEY": "test-key",
}


def media_payload(
    *,
    phone: str = CUSTOMER_PHONE,
    tipo: str = "audio",
    provider_media_id: str = "MEDIA_ID",
    mime_type: str | None = "audio/ogg",
    caption: str | None = None,
    message_id: str = "wamid.media-1",
) -> dict:
    """Same shape `InboundMessage.to_payload()` produces for a media event
    (`whatbot/channels/base.py`) — `text` empty, `media` populated."""
    return {
        "canal": WHATSAPP,
        "external_id": phone,
        "from_number": phone,
        "text": "",
        "push_name": "Maria",
        "message_id": message_id,
        "media": {
            "tipo": tipo,
            "provider_media_id": provider_media_id,
            "mime_type": mime_type,
            "caption": caption,
        },
    }


class MediaHandlingTestCase(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.wa = FakeClient(WHATSAPP)
        self.router = ChannelRouter([self.wa])
        self.llm = FakeLlm(reply="não deveria ser chamado")

        # Isola o storage num diretório temporário — sem isso,
        # `get_storage_backend()` gravaria de verdade em `./data/media`
        # (default de `MEDIA_STORAGE_ROOT`), poluindo o working dir do repo.
        self._tmp_storage = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_storage.cleanup)

        patches = [
            patch.object(main_mod, "_db", self.db),
            patch.object(main_mod, "_router", self.router),
            patch.object(main_mod, "_llm", self.llm),
            patch.object(main_mod, "_init_infra", lambda: None),
            patch.dict(
                os.environ,
                {**BASE_ENV, "MEDIA_STORAGE_ROOT": self._tmp_storage.name},
                clear=False,
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        storage_factory._cached_backend = None
        storage_factory._cached_backend_key = None
        self.addCleanup(self._reset_storage_cache)

    @staticmethod
    def _reset_storage_cache() -> None:
        storage_factory._cached_backend = None
        storage_factory._cached_backend_key = None


class TestMediaDownloadSuccess(MediaHandlingTestCase):
    def test_media_is_downloaded_stored_and_referenced(self):
        self.wa.download_media = lambda media_id: (b"audio bytes", "audio/ogg")

        result = main_mod.main(media_payload())

        self.assertTrue(result["ok"])
        self.assertTrue(result.get("media_only"))
        self.assertEqual(result["media_status"], "baixado")

        media_id = result["media_id"]
        media_file = self.db.get_media_file(media_id)
        self.assertIsNotNone(media_file)
        self.assertEqual(media_file.status, "baixado")
        self.assertEqual(media_file.tipo, "audio")
        self.assertEqual(media_file.origem_media_id, "MEDIA_ID")

        contact = self.db.get_contact_by_phone(CUSTOMER_PHONE, canal=WHATSAPP)
        messages = self.db.get_conversation(contact.id)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].media_id, media_id)
        self.assertEqual(messages[0].canal, WHATSAPP)

        # Não passa pelo pipeline de LLM (mensagem sem texto) — ver
        # proposal.md "Fora de escopo".
        self.assertEqual(self.wa.sent, [])

    def test_caption_is_persisted_as_message_text(self):
        self.wa.download_media = lambda media_id: (b"jpeg bytes", "image/jpeg")

        main_mod.main(media_payload(tipo="image", caption="olha isso"))

        contact = self.db.get_contact_by_phone(CUSTOMER_PHONE, canal=WHATSAPP)
        messages = self.db.get_conversation(contact.id)
        self.assertEqual(messages[0].text, "olha isso")


class TestMediaDownloadFailure(MediaHandlingTestCase):
    """Requirement "Falha de download não bloqueia a mensagem"."""

    def test_download_error_still_records_the_message(self):
        self.wa.download_media = lambda media_id: (_ for _ in ()).throw(
            ChannelError(WHATSAPP, "token expirado")
        )

        result = main_mod.main(media_payload())

        self.assertTrue(result["ok"])
        self.assertEqual(result["media_status"], "falhou")

        media_file = self.db.get_media_file(result["media_id"])
        self.assertEqual(media_file.status, "falhou")
        self.assertIsNotNone(media_file.erro)

        contact = self.db.get_contact_by_phone(CUSTOMER_PHONE, canal=WHATSAPP)
        messages = self.db.get_conversation(contact.id)
        self.assertEqual(len(messages), 1, "a mensagem é registrada mesmo com falha de download")

    def test_channel_without_download_media_support_fails_gracefully(self):
        # `self.wa.download_media` stays `None` (default) — mimics
        # `EvolutionApiClient`, que não implementa download de mídia.
        result = main_mod.main(media_payload())

        self.assertTrue(result["ok"])
        self.assertEqual(result["media_status"], "falhou")


class TestMediaMessageDuplicateDelivery(MediaHandlingTestCase):
    def test_redelivered_media_event_is_discarded_as_duplicate(self):
        self.wa.download_media = lambda media_id: (b"x", "audio/ogg")
        payload = media_payload(message_id="wamid.dup-media")

        first = main_mod.main(payload)
        second = main_mod.main(payload)

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(second.get("reason"), "duplicate_message_id")

        contact = self.db.get_contact_by_phone(CUSTOMER_PHONE, canal=WHATSAPP)
        self.assertEqual(len(self.db.get_conversation(contact.id)), 1)


if __name__ == "__main__":
    unittest.main()
