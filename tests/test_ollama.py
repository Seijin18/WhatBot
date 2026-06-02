import unittest
from unittest.mock import MagicMock, patch

from whatbot.db import MessageRecord
from whatbot.llm import LlmUnavailableError
from whatbot.ollama_client import OllamaClient
from whatbot.prompt_builder import build_enriched_system_prompt


class TestPromptBuilder(unittest.TestCase):
    def test_enriched_contains_modalidades(self):
        prompt = build_enriched_system_prompt("Você é um assistente.")
        self.assertIn("Judô", prompt)
        self.assertIn("Kannon", prompt)
        self.assertIn("BASE DE CONHECIMENTO", prompt)


class TestOllamaClient(unittest.TestCase):
    @patch("whatbot.ollama_client.requests.post")
    def test_chat_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "message": {"content": "Temos judô e yoga na associação."}
        }
        mock_post.return_value = mock_resp

        client = OllamaClient(base_url="http://localhost:11434", model="llama3.2")
        reply = client.chat(
            "Assistente de vendas.",
            [
                MessageRecord(1, 1, "in", "Olá", None),
            ],
            "Quais modalidades?",
        )
        self.assertIn("judô", reply.lower())
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "llama3.2")
        self.assertFalse(payload["stream"])

    @patch("whatbot.ollama_client.requests.post")
    def test_connection_error(self, mock_post):
        import requests

        mock_post.side_effect = requests.ConnectionError("refused")
        client = OllamaClient()
        with self.assertRaises(LlmUnavailableError):
            client.chat("sys", [], "oi")


if __name__ == "__main__":
    unittest.main()
