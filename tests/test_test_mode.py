import os
import unittest
from unittest.mock import patch

from whatbot.config import (
    get_test_identities,
    get_test_phones,
    is_test_mode,
    is_test_phone,
    should_respond_to_customer,
)


class TestTestMode(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_test_mode_disabled_by_default(self):
        os.environ.pop("TEST_MODE", None)
        self.assertFalse(is_test_mode())
        self.assertTrue(should_respond_to_customer("5511999999999"))

    def test_test_mode_restricts_unknown_phones(self):
        os.environ["TEST_MODE"] = "true"
        os.environ["TEST_PHONES"] = "5511888888888,5511777777777"
        self.assertTrue(is_test_mode())
        self.assertEqual(get_test_phones(), ["5511888888888", "5511777777777"])
        self.assertTrue(is_test_phone("5511888888888"))
        self.assertTrue(is_test_phone("5511888888888@s.whatsapp.net"))
        self.assertTrue(should_respond_to_customer("5511888888888"))
        self.assertFalse(should_respond_to_customer("5511999999999"))

    def test_each_channel_has_its_own_test_list(self):
        """Requirement 'Filtro de teste por canal' — TEST_MODE com lista própria."""
        os.environ["TEST_MODE"] = "true"
        os.environ["TEST_PHONES"] = "5511888888888"
        os.environ["TEST_IGSIDS"] = "17841400000000000"

        self.assertTrue(should_respond_to_customer("5511888888888", canal="whatsapp"))
        self.assertTrue(
            should_respond_to_customer("17841400000000000", canal="instagram")
        )
        self.assertFalse(
            should_respond_to_customer("17841499999999999", canal="instagram")
        )

    def test_channel_without_test_list_fails_closed(self):
        """Requirement 'Filtro de teste por canal' — sem lista, bloqueia por padrão."""
        os.environ["TEST_MODE"] = "true"
        os.environ.pop("TEST_PHONES", None)
        os.environ.pop("TEST_IGSIDS", None)

        self.assertEqual(get_test_identities("instagram"), [])
        self.assertFalse(
            should_respond_to_customer("17841400000000000", canal="instagram")
        )
        self.assertFalse(should_respond_to_customer("5511999999999", canal="whatsapp"))

    def test_test_list_of_one_channel_does_not_leak_into_another(self):
        """Requirement 'Filtro de teste por canal' — a lista de um canal não
        vaza para outro, mesmo com as duas listas configuradas
        simultaneamente e um identificador que aparece na lista "errada"."""
        os.environ["TEST_MODE"] = "true"
        # Both lists configured at once, each containing the *other*
        # channel's identity too — this is the actual crossing scenario
        # (design.md, Importante 6): a phone that also happens to be listed
        # as an allowed IGSID, and vice versa.
        shared_value = "17841400000000000"
        os.environ["TEST_PHONES"] = f"5511888888888,{shared_value}"
        os.environ["TEST_IGSIDS"] = "999999999,5511888888888"

        # `shared_value` is on the WhatsApp list, but Instagram's own list
        # does not contain it — Instagram must not honor WhatsApp's list.
        self.assertFalse(
            should_respond_to_customer(shared_value, canal="instagram")
        )
        # `5511888888888` is on the Instagram list (as a raw string), but
        # WhatsApp must not honor Instagram's list — it does have its own
        # entry for this number though, so it still resolves True from its
        # *own* list, not by leaking from Instagram's.
        self.assertTrue(
            should_respond_to_customer("5511888888888", canal="whatsapp")
        )
        # An identity present only in the *other* channel's list must be
        # blocked, proving the comparison never crosses channels.
        self.assertFalse(should_respond_to_customer("999999999", canal="whatsapp"))
        self.assertFalse(
            should_respond_to_customer(shared_value, canal="instagram")
        )
        self.assertTrue(
            should_respond_to_customer(shared_value, canal="whatsapp")
        )

    @patch("whatbot.main._init_infra")
    @patch("whatbot.main.is_admin_phone", return_value=False)
    @patch("whatbot.main.process_customer_message")
    def test_main_ignores_non_test_phone(self, process_msg, _is_admin, _init):
        os.environ["TEST_MODE"] = "true"
        os.environ["TEST_PHONES"] = "5511888888888"
        from whatbot.main import main

        result = main({"from_number": "5511999999999", "text": "Olá"})
        self.assertTrue(result.get("ignored"))
        self.assertEqual(result.get("reason"), "test_mode")
        process_msg.assert_not_called()

    @patch("whatbot.main._init_infra")
    @patch("whatbot.main.is_admin_phone", return_value=False)
    @patch("whatbot.main.process_customer_message", return_value={"ok": True})
    def test_main_allows_test_phone(self, process_msg, _is_admin, _init):
        os.environ["TEST_MODE"] = "true"
        os.environ["TEST_PHONES"] = "5511888888888"
        from whatbot.main import main

        result = main({"from_number": "5511888888888", "text": "Olá"})
        self.assertNotEqual(result.get("reason"), "test_mode")
        process_msg.assert_called_once()


if __name__ == "__main__":
    unittest.main()
