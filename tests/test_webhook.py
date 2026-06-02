import unittest

from whatbot.webhook import parse_evolution_payload


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


if __name__ == "__main__":
    unittest.main()
