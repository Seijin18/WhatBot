"""Tests for `whatbot/main.py::_init_infra()`'s WhatsApp provider selection.

Unlike `tests/test_main_e2e.py`, which patches `_init_infra` away entirely
(`patch.object(main_mod, "_init_infra", lambda: None)`) to test the domain
flow in isolation, this file calls `_init_infra()` for real to exercise the
`WHATSAPP_PROVIDER` branch itself — the registration logic added by
`whatsapp-cloud-channel-client`. `_db` is pre-set to a `FakeDatabase` and
`_llm` to a sentinel so no real Postgres/LLM client is ever built; only the
router-registration branch runs for real.
"""

import os
import unittest
from unittest.mock import patch

from fakes import FakeDatabase

from whatbot import main as main_mod
from whatbot.channels import WHATSAPP, EvolutionApiClient, WhatsAppCloudClient


class TestWhatsAppProviderSelection(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        patches = [
            patch.object(main_mod, "_db", self.db),
            patch.object(main_mod, "_router", None),
            patch.object(main_mod, "_llm", object()),  # non-None: skips create_llm_client()
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _env(self, **overrides):
        base = {
            "EVOLUTION_API_KEY": "real-key",
            "EVOLUTION_API_INSTANCE_NAME": "whatbot",
        }
        base.update(overrides)
        return patch.dict(os.environ, base, clear=False)

    def test_provider_unset_keeps_todays_evolution_behavior(self):
        # Requirement "Provedor não configurado mantém o comportamento
        # atual" — no regression for the default path.
        with self._env(WHATSAPP_PROVIDER=""):
            main_mod._init_infra()

        client = main_mod._router.client_for(WHATSAPP)
        self.assertIsInstance(client, EvolutionApiClient)

    def test_explicit_evolution_provider_still_fails_loud_without_env(self):
        with self._env(
            WHATSAPP_PROVIDER="evolution",
            EVOLUTION_API_KEY="",
            EVOLUTION_API_INSTANCE_NAME="",
        ):
            with self.assertRaises(RuntimeError):
                main_mod._init_infra()

        # Same as today's behavior: a failed registration leaves _router
        # unset, so a retry after fixing the env is still possible.
        self.assertIsNone(main_mod._router)

    def test_cloud_provider_registers_cloud_client_from_credential(self):
        self.db.upsert_channel_credential(
            WHATSAPP, "wa-token", account_id="1234567890"
        )
        with self._env(WHATSAPP_PROVIDER="cloud"):
            main_mod._init_infra()

        client = main_mod._router.client_for(WHATSAPP)
        self.assertIsInstance(client, WhatsAppCloudClient)
        self.assertEqual(client.access_token, "wa-token")
        self.assertEqual(client.phone_number_id, "1234567890")

    def test_cloud_provider_without_credential_fails_loud(self):
        with self._env(WHATSAPP_PROVIDER="cloud"):
            with self.assertRaises(RuntimeError):
                main_mod._init_infra()

        # Same retry-ability guarantee as the Evolution failure path above.
        self.assertIsNone(main_mod._router)

    def test_cloud_provider_credential_without_account_id_fails_loud(self):
        # account_id (phone_number_id) is required to build the messages
        # URL — a token alone is not enough to register the client.
        self.db.upsert_channel_credential(WHATSAPP, "wa-token", account_id=None)
        with self._env(WHATSAPP_PROVIDER="cloud"):
            with self.assertRaises(RuntimeError):
                main_mod._init_infra()


if __name__ == "__main__":
    unittest.main()
