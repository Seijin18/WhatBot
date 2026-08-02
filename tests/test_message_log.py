import json
import logging
import os
import tempfile
import unittest
from pathlib import Path

from whatbot.message_log import (
    log_inbound,
    log_llm_turn,
    log_outbound,
    resolve_message_log_path,
)


class TestMessageLog(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.log_path = Path(self._tmpdir.name) / "messages.jsonl"
        os.environ["WHATBOT_MESSAGE_LOG_PATH"] = str(self.log_path)
        os.environ["WHATBOT_MESSAGE_LOG_MAX_CHARS"] = "100"

    def tearDown(self) -> None:
        os.environ.pop("WHATBOT_MESSAGE_LOG_PATH", None)
        os.environ.pop("WHATBOT_MESSAGE_LOG_MAX_CHARS", None)
        self._tmpdir.cleanup()

    def test_log_inbound_writes_jsonl(self) -> None:
        with self.assertLogs("whatbot.messages", level="INFO") as captured:
            log_inbound(
                "5511999999999",
                "Olá, quero saber sobre yoga",
                push_name="Maria",
                contact_id=1,
            )

        self.assertTrue(self.log_path.exists())
        entry = json.loads(self.log_path.read_text(encoding="utf-8").strip())
        self.assertEqual(entry["direction"], "in")
        self.assertEqual(entry["phone"], "5511999999999")
        self.assertEqual(entry["canal"], "whatsapp")
        self.assertEqual(entry["source"], "customer")
        self.assertIn("Olá", entry["text"])
        self.assertTrue(any("dir=in" in line for line in captured.output))
        self.assertTrue(any("canal=whatsapp" in line for line in captured.output))

    def test_log_inbound_records_a_non_whatsapp_canal(self) -> None:
        log_inbound(
            "17841400000000000",
            "Olá pelo Instagram",
            canal="instagram",
            contact_id=1,
        )

        entry = json.loads(self.log_path.read_text(encoding="utf-8").strip())
        self.assertEqual(entry["canal"], "instagram")
        self.assertEqual(entry["phone"], "17841400000000000")

    def test_log_outbound_truncates_long_text(self) -> None:
        long_text = "x" * 200
        log_outbound("5511888888888", long_text, source="bot", delivery="sent")

        entry = json.loads(self.log_path.read_text(encoding="utf-8").strip())
        self.assertEqual(entry["text_len"], 200)
        self.assertIn("… (+100 chars)", entry["text"])
        self.assertEqual(entry["canal"], "whatsapp")

    def test_log_llm_turn_records_fallback(self) -> None:
        log_llm_turn(
            "5511999999999",
            "Quanto custa?",
            "Consulte a secretaria.",
            canal="instagram",
            used_fallback=True,
            llm_provider="ollama",
            llm_model="qwen2.5:7b-instruct-q4_K_M",
        )

        entry = json.loads(self.log_path.read_text(encoding="utf-8").strip())
        self.assertEqual(entry["kind"], "llm")
        self.assertTrue(entry["used_fallback"])
        self.assertEqual(entry["llm_provider"], "ollama")
        self.assertEqual(entry["canal"], "instagram")

    def test_no_file_when_path_unset(self) -> None:
        os.environ["WHATBOT_MESSAGE_LOG_PATH"] = ""
        log_inbound("5511", "teste")
        self.assertFalse(self.log_path.exists())

    def test_resolve_relative_path_against_project_root(self) -> None:
        root = Path(__file__).resolve().parent.parent
        resolved = resolve_message_log_path("logs/messages.jsonl")
        self.assertEqual(resolved, root / "logs/messages.jsonl")


if __name__ == "__main__":
    unittest.main()
