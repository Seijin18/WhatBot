import os
import unittest
from unittest.mock import patch

from whatbot.config import (
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
