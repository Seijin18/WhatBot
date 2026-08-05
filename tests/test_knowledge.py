import unittest

from whatbot.knowledge import _parse_markdown
from whatbot import tools
from tests.kb_fixtures import (
    CATALOG_KB,
    CLASS_SCHEDULE_KB,
    load_catalog_kb,
    load_class_schedule_kb,
)


class TestKnowledgeParser(unittest.TestCase):
    def test_parse_itens_and_faq(self):
        base = _parse_markdown(CLASS_SCHEDULE_KB)

        self.assertIn("yoga", base.itens)
        self.assertEqual(
            base.itens["yoga"].campos["Horários"],
            "Quartas-feiras, das 19:30 às 20:30",
        )
        self.assertIn("judo infantil", base.itens)
        self.assertTrue(base.faq)
        self.assertIn("sobre", base.secoes)

    def test_store_reload_on_access(self):
        store = load_class_schedule_kb()
        itens = store.listar_itens()
        self.assertIn("Yoga", itens)
        self.assertIn("Judô infantil", itens)

    def test_buscar_horarios(self):
        store = load_class_schedule_kb()
        res = store.buscar_horarios("yoga")
        self.assertIn("19:30", res)

    def test_buscar_precos_tabela(self):
        store = load_class_schedule_kb()
        res = store.buscar_precos(None)
        self.assertIn("R$ 150", res)
        self.assertIn("R$ 840", res)
        self.assertIn("Aula experimental", res)

    def test_buscar_faq(self):
        store = load_class_schedule_kb()
        res = store.buscar_faq("aula experimental")
        self.assertIn("experimental", res.lower())

    def test_buscar_faq_chinelo(self):
        store = load_class_schedule_kb()
        res = store.buscar_faq("chinelo")
        self.assertIn("judô", res.lower())
        self.assertIn("yoga", res.lower())

    def test_parse_catalog_without_itens(self):
        """A KB with no `## Itens` section (product catalog, not class
        schedules) must still parse cleanly — `itens` stays empty rather
        than erroring, and `Preços`/`Como comprar e pagamento` parse as
        plain sections."""
        base = _parse_markdown(CATALOG_KB)
        self.assertEqual(base.itens, {})
        self.assertIn("precos", base.secoes)
        self.assertIn("como comprar e pagamento", base.secoes)
        self.assertTrue(base.faq)

    def test_buscar_precos_catalog_has_no_item_heading(self):
        """`buscar_precos()` must not print the per-item table header when
        there are no itens — it used to appear with nothing under it for a
        catalog-style business (see docs/REVISAO_CAMADA_CONVERSACIONAL.md,
        P1.1)."""
        store = load_catalog_kb()
        res = store.buscar_precos(None)
        self.assertNotIn("Tabela de preços por item", res)
        self.assertIn("R$ 39,90", res)

    def test_listar_itens_falls_back_to_precos_for_catalog(self):
        """A catalog-style business has no `## Itens` section, so the
        "what do you have?" answer must fall back to the price table
        instead of "Nenhum item cadastrado no momento." — that
        placeholder used to be sent to the customer verbatim (see
        docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.1/P1.3)."""
        store = load_catalog_kb()
        res = store.listar_itens()
        self.assertNotIn("Nenhum item cadastrado", res)
        self.assertIn("R$ 39,90", res)

    def test_buscar_faq_uses_real_section_heading(self):
        """FAQ/section titles come from the file's own heading text, not a
        hardcoded translation (see docs/REVISAO_CAMADA_CONVERSACIONAL.md,
        P1.1 — the previous code always printed a fixed translated header
        even when it didn't describe the section's content)."""
        store = load_catalog_kb()
        res = store.buscar_info("como comprar")
        self.assertIn("Como comprar e pagamento:", res)
        self.assertIn("Como encomendar", res)


class TestAgentTools(unittest.TestCase):
    def setUp(self):
        load_class_schedule_kb()

    def test_listar_itens_tool(self):
        res = tools.listar_itens()
        self.assertIn("Yoga", res)
        self.assertIn("Judô", res)

    def test_buscar_horarios_turmas_tool(self):
        res = tools.buscar_horarios_turmas("judô infantil")
        self.assertIn("18:30", res)

    def test_execute_tool(self):
        res = tools.execute_tool("buscar_info_negocio", {"topico": "como comprar"})
        self.assertIn("experimental", res.lower())


if __name__ == "__main__":
    unittest.main()
