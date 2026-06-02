import unittest
from pathlib import Path

from whatbot.claim_validator import ClaimValidator
from whatbot.grounding import (
    build_knowledge_reply,
    detect_hallucination,
    ensure_grounded_reply,
)
from whatbot.intent_router import INTENT_PRECOS, route_intent
from whatbot.knowledge import KnowledgeStore, get_knowledge_store
from whatbot.knowledge_facts import build_facts_from_base, norm_text, reset_knowledge_facts_cache
from whatbot.prompt_builder import build_context_for_intent, build_enriched_system_prompt
from whatbot.reply_composer import ReplyComposer
from whatbot.session_state import SessionState, update_session_state

KNOWLEDGE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "associacao.md"


def _load_store() -> KnowledgeStore:
    store = get_knowledge_store()
    store._path = KNOWLEDGE_PATH
    store.reload()
    reset_knowledge_facts_cache()
    return store


class TestKnowledgeFacts(unittest.TestCase):
    def setUp(self) -> None:
        _load_store()

    def test_experimental_days_from_markdown(self) -> None:
        facts = build_facts_from_base(get_knowledge_store().get())
        self.assertEqual(facts.experimental_days_for("judô"), ["quinta"])
        self.assertEqual(facts.experimental_days_for("yoga"), ["quarta"])
        self.assertEqual(len(facts.experimental_slots), 2)
        self.assertEqual(facts.monthly_price, 150)
        self.assertFalse(facts.experimental_has_price)
        self.assertIn("experimental", facts.high_risk_intents)
        self.assertIn("precos", facts.high_risk_intents)

    def test_adapts_to_new_modality_in_knowledge(self) -> None:
        store = get_knowledge_store()
        text = store._path.read_text(encoding="utf-8")
        augmented = text.replace(
            "- Dias disponíveis para aula experimental de yoga: quarta-feira (4ªf)",
            "- Dias disponíveis para aula experimental de yoga: quarta-feira (4ªf)\n"
            "- Aula experimental de pilates: segunda-feira",
        ).replace(
            "## Preços",
            "### Pilates\n\n- Horários: Segundas, 10h\n- Preço mensal: R$ 120\n\n## Preços",
        )
        store.reload_from_text(augmented)
        reset_knowledge_facts_cache()
        facts = build_facts_from_base(store.get())
        self.assertTrue(any("pilates" in norm_text(slot.label) for slot in facts.experimental_slots))
        self.assertEqual(facts.experimental_days_for("Pilates"), ["segunda"])
        self.assertIn("Pilates", facts.match_modalidades("quero pilates"))


class TestClaimValidator(unittest.TestCase):
    def setUp(self) -> None:
        store = _load_store()
        self.facts = build_facts_from_base(store.get())
        self.validator = ClaimValidator(self.facts)

    def test_rejects_experimental_on_tuesday_with_price(self) -> None:
        session = SessionState(modalidade_interesse=["judo"], topico_atual="experimental")
        reply = (
            "Para a aula experimental de judô na terça-feira, você pode comparecer às 18:30. "
            "A aula experimental custa R$ 150 por aluno."
        )
        result = self.validator.validate(reply, "Quero na terça feira", session)
        self.assertFalse(result.valid)
        self.assertTrue(any("terça" in v or "experimental" in v.lower() for v in result.violations))

    def test_rejects_experimental_price_only(self) -> None:
        reply = "O preço para uma aula experimental de judô é R$ 150 por aluno."
        result = self.validator.validate(reply, "Qual o preço?", SessionState())
        self.assertFalse(result.valid)

    def test_accepts_regular_schedule(self) -> None:
        reply = (
            "Judô infantil: terças e quintas, das 18:30 às 19:30. "
            "Plano mensal R$ 150 (1 aluno)."
        )
        result = self.validator.validate(reply, "horários", SessionState())
        self.assertTrue(result.valid)


class TestGrounding(unittest.TestCase):
    def setUp(self) -> None:
        _load_store()

    def test_detect_hallucinated_modalities(self) -> None:
        bad = (
            "Temos futebol society, basquete e yoga às segundas e quintas às 19h30."
        )
        self.assertTrue(detect_hallucination(bad))

    def test_detect_wrong_association_name(self) -> None:
        bad = "Olá! O TimeVivo é uma associação desportiva e cultural."
        self.assertTrue(detect_hallucination(bad))

    def test_accepts_new_modality_when_in_knowledge(self) -> None:
        store = get_knowledge_store()
        store._path = KNOWLEDGE_PATH
        text = store._path.read_text(encoding="utf-8")
        augmented = text.replace(
            "## Preços",
            "### Pilates\n\n- Horários: Segundas, 10h\n- Preço mensal: R$ 120\n\n## Preços",
        )
        store.reload_from_text(augmented)
        reset_knowledge_facts_cache()
        good = "Temos pilates às segundas às 10h por R$ 120."
        self.assertFalse(detect_hallucination(good))

    def test_build_knowledge_reply_about_association(self) -> None:
        reply = build_knowledge_reply("Quem é o timevivo?")
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertIn("Kannon", reply)
        self.assertNotIn("TimeVivo", reply)
        self.assertNotIn("futebol", reply.lower())

    def test_build_knowledge_reply_lists_only_real_modalities(self) -> None:
        reply = build_knowledge_reply("Que modalidades você tem?")
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertIn("Judô infantil", reply)
        self.assertIn("Yoga", reply)
        self.assertNotIn("basquete", reply.lower())
        self.assertNotIn("futebol", reply.lower())

    def test_ensure_grounded_reply_replaces_hallucination(self) -> None:
        bad = "O TimeVivo oferece futebol e meditação."
        final, corrected, meta = ensure_grounded_reply(bad, "Quem é o timevivo?")
        self.assertTrue(corrected)
        self.assertNotIn("TimeVivo", final)
        self.assertNotIn("futebol", final.lower())
        self.assertIn("Kannon", final)
        self.assertEqual(meta.get("response_mode"), "grounding_fix")

    def test_log_regression_terca_experimental(self) -> None:
        session = SessionState(
            modalidade_interesse=["judo"],
            topico_atual="precos",
            aguardando_dados_experimental=False,
        )
        bad = (
            "Para a aula experimental de judô na terça-feira, você pode comparecer às 18:30. "
            "A aula experimental custa R$ 150 por aluno."
        )
        final, corrected, _ = ensure_grounded_reply(
            bad, "Quero na terça feira", session
        )
        self.assertTrue(corrected)
        self.assertIn("quinta", final.lower())
        self.assertNotIn("terça-feira", final.lower())

    def test_log_regression_preco_experimental(self) -> None:
        bad = "O preço para uma aula experimental de judô é R$ 150 por aluno."
        final, corrected, _ = ensure_grounded_reply(bad, "Qual o preço?", SessionState())
        self.assertTrue(corrected)
        self.assertIn("mensal", final.lower())
        self.assertNotIn("experimental de judô é R$ 150", final.lower())

    def test_log_regression_judo_e_yoga_precos(self) -> None:
        session = SessionState(modalidade_interesse=["judo", "yoga"], topico_atual="precos")
        intent = route_intent("Do judo e do yoga?", session)
        self.assertEqual(intent.intent, INTENT_PRECOS)
        composer = ReplyComposer(build_facts_from_base(get_knowledge_store().get()))
        reply = composer.compose(intent, "Do judo e do yoga?", session)
        assert reply is not None
        self.assertIn("judô", reply.lower())
        self.assertIn("yoga", reply.lower())
        self.assertIn("150", reply)
        self.assertLess(len(reply), 900)


class TestPromptGrounding(unittest.TestCase):
    def setUp(self) -> None:
        _load_store()

    def test_enriched_prompt_derives_rules_from_knowledge(self) -> None:
        prompt = build_enriched_system_prompt("Assistente.")
        self.assertIn("Kannon", prompt)
        self.assertIn("Judô infantil", prompt)
        self.assertIn("REGRAS DE ATENDIMENTO", prompt)
        self.assertNotIn("futebol", prompt.lower())

    def test_context_chunks_smaller_than_full_dump(self) -> None:
        store = get_knowledge_store()
        full = len(store.format_full_context_for_prompt())
        intent = route_intent("Qual o preço do judô?", SessionState())
        chunk = build_context_for_intent(intent, SessionState())
        self.assertLess(len(chunk), full)


class TestIntentRouter(unittest.TestCase):
    def test_terca_after_judo_interest_routes_experimental(self) -> None:
        session = update_session_state(
            SessionState(modalidade_interesse=["judo"], topico_atual="precos"),
            "Quero na terça feira",
            "precos",
        )
        intent = route_intent("Quero na terça feira", session)
        self.assertEqual(intent.intent, "experimental")


if __name__ == "__main__":
    unittest.main()
