import unittest
from pathlib import Path

from whatbot.knowledge import KnowledgeStore, _parse_markdown, get_knowledge_store
from whatbot import tools


KNOWLEDGE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "associacao.md"


class TestKnowledgeParser(unittest.TestCase):
    def test_parse_modalidades_and_faq(self):
        text = KNOWLEDGE_PATH.read_text(encoding="utf-8")
        base = _parse_markdown(text)

        self.assertIn("yoga", base.modalidades)
        self.assertEqual(
            base.modalidades["yoga"].campos["Horários"],
            "Quartas-feiras, das 19:30 às 20:30",
        )
        self.assertIn("judo infantil", base.modalidades)
        self.assertTrue(base.faq)
        self.assertIn("sobre a associacao", base.secoes)

    def test_store_reload_on_access(self):
        store = KnowledgeStore(KNOWLEDGE_PATH)
        modalidades = store.listar_modalidades()
        self.assertIn("Yoga", modalidades)
        self.assertIn("Judô infantil", modalidades)

    def test_buscar_horarios(self):
        store = KnowledgeStore(KNOWLEDGE_PATH)
        res = store.buscar_horarios("yoga")
        self.assertIn("19:30", res)

    def test_buscar_precos_tabela(self):
        store = KnowledgeStore(KNOWLEDGE_PATH)
        res = store.buscar_precos(None)
        self.assertIn("R$ 150", res)
        self.assertIn("R$ 840", res)
        self.assertIn("Aula experimental", res)

    def test_buscar_faq(self):
        store = KnowledgeStore(KNOWLEDGE_PATH)
        res = store.buscar_faq("aula experimental")
        self.assertIn("experimental", res.lower())

    def test_buscar_faq_chinelo(self):
        store = KnowledgeStore(KNOWLEDGE_PATH)
        res = store.buscar_faq("chinelo")
        self.assertIn("judô", res.lower())
        self.assertIn("yoga", res.lower())


class TestAgentTools(unittest.TestCase):
    def setUp(self):
        store = get_knowledge_store()
        store._path = KNOWLEDGE_PATH
        store.reload()

    def test_listar_modalidades_tool(self):
        res = tools.listar_modalidades()
        self.assertIn("Yoga", res)
        self.assertIn("Judô", res)

    def test_buscar_horarios_turmas_tool(self):
        res = tools.buscar_horarios_turmas("judô infantil")
        self.assertIn("18:30", res)

    def test_execute_tool(self):
        res = tools.execute_tool("buscar_info_associacao", {"topico": "matrícula"})
        self.assertIn("experimental", res.lower())


if __name__ == "__main__":
    unittest.main()
