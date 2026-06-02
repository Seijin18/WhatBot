import unittest

from whatbot import domain, tools


class TestDomainFunctions(unittest.TestCase):
    def test_buscar_horarios_turmas_known(self):
        res = tools.buscar_horarios_turmas("yoga")
        self.assertIn("19:30", res)

    def test_buscar_horarios_turmas_unknown(self):
        res = tools.buscar_horarios_turmas("boxe")
        self.assertIsInstance(res, str)
        self.assertTrue(len(res) > 0)

    def test_detectar_pedido_atendimento_humano(self):
        self.assertTrue(domain.detectar_pedido_atendimento_humano("Quero falar com a secretaria"))
        self.assertFalse(domain.detectar_pedido_atendimento_humano("Qual o horário da secretaria?"))

    def test_detectar_intencao_human_handoff_token(self):
        self.assertTrue(
            domain.detectar_intencao_human_handoff("Por favor [HUMAN_HANDOVER]")
        )

    def test_detectar_intencao_human_handoff_keywords_no_longer_trigger(self):
        self.assertFalse(
            domain.detectar_intencao_human_handoff(
                "Para valores, consulte a secretaria. Temos judô e yoga."
            )
        )
        self.assertFalse(
            domain.detectar_intencao_human_handoff("Quero falar com um atendente sobre horários")
        )

    def test_detectar_intencao_human_handoff_false(self):
        self.assertFalse(
            domain.detectar_intencao_human_handoff(
                "Informações sobre horários, por favor"
            )
        )

    def test_build_handover_customer_message(self):
        msg = domain.build_handover_customer_message(
            "Não tenho o valor da mensalidade na base.\n[HUMAN_HANDOVER]"
        )
        self.assertIn("Não tenho o valor", msg)
        self.assertIn("secretaria dará continuidade", msg)
        self.assertNotIn("[HUMAN_HANDOVER]", msg)

    def test_strip_handover_token(self):
        self.assertEqual(
            domain.strip_handover_token("Olá [HUMAN_HANDOVER]"),
            "Olá",
        )


if __name__ == "__main__":
    unittest.main()
