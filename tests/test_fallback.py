import unittest

from whatbot.db import MessageRecord
from whatbot.fallback import build_knowledge_fallback, trim_history_for_chat


class TestFallback(unittest.TestCase):
    def test_trim_duplicate_inbound(self):
        history = [
            MessageRecord(3, 1, "in", "Quero judô", None),
            MessageRecord(2, 1, "out", "Olá", None),
            MessageRecord(1, 1, "in", "Oi", None),
        ]
        trimmed = trim_history_for_chat(history, "Quero judô")
        self.assertEqual(len(trimmed), 2)
        self.assertEqual(trimmed[0].text, "Olá")

    def test_judo_fallback(self):
        reply = build_knowledge_fallback("Quero mais informações das aulas de judô")
        self.assertIsNotNone(reply)
        self.assertIn("18:30", reply)
        self.assertIn("20:00", reply)
        self.assertNotIn("P:", reply)
        self.assertIn("instabilidade", reply.lower())
        self.assertNotIn("gemini", reply.lower())
        self.assertNotIn("aistudio", reply.lower())

    def test_modalidades_fallback(self):
        reply = build_knowledge_fallback("Quais modalidades vocês têm?")
        self.assertIsNotNone(reply)
        self.assertIn("Judô", reply)

    def test_quota_fallback_sem_detalhes_tecnicos(self):
        reply = build_knowledge_fallback("Quero judô", reason="quota")
        self.assertIsNotNone(reply)
        self.assertNotIn("gemini", reply.lower())
        self.assertNotIn("cota", reply.lower())
        self.assertNotIn("aistudio", reply.lower())
        self.assertIn("secretaria", reply.lower())


if __name__ == "__main__":
    unittest.main()
