"""`whatbot.session_state.next_status` — automatic contact stage transitions
(contact-interest-memory). `SessionState`/`update_session_state` already have
coverage through `tests/test_main_e2e.py`; this file focuses on the pure
`next_status` function."""

import unittest

from whatbot.intent_router import INTENT_GREETING, INTENT_PEDIDO
from whatbot.session_state import SessionState, next_status


class TestNextStatusAdvancesToInteressado(unittest.TestCase):
    def test_novo_lead_becomes_interessado_when_item_interesse_appears(self):
        session = SessionState(item_interesse=["natação"])

        result = next_status("novo_lead", session, INTENT_GREETING, has_order=False)

        self.assertEqual(result, "interessado")

    def test_novo_lead_stays_novo_lead_without_item_interesse(self):
        session = SessionState(item_interesse=[])

        result = next_status("novo_lead", session, INTENT_GREETING, has_order=False)

        self.assertIsNone(result)

    def test_interessado_does_not_regress_or_repeat_on_a_neutral_message(self):
        session = SessionState(item_interesse=["natação"])

        result = next_status("interessado", session, INTENT_GREETING, has_order=False)

        self.assertIsNone(result)


class TestNextStatusAdvancesToComprando(unittest.TestCase):
    def test_becomes_comprando_with_intent_pedido(self):
        session = SessionState(item_interesse=["natação"])

        result = next_status("interessado", session, INTENT_PEDIDO, has_order=False)

        self.assertEqual(result, "comprando")

    def test_becomes_comprando_with_has_order_even_without_intent_pedido(self):
        session = SessionState(item_interesse=[])

        result = next_status("novo_lead", session, INTENT_GREETING, has_order=True)

        self.assertEqual(result, "comprando")

    def test_novo_lead_jumps_straight_to_comprando_on_intent_pedido(self):
        session = SessionState(item_interesse=[])

        result = next_status("novo_lead", session, INTENT_PEDIDO, has_order=False)

        self.assertEqual(result, "comprando")


class TestNextStatusNeverRegresses(unittest.TestCase):
    def test_comprando_stays_comprando_on_a_neutral_message(self):
        session = SessionState(item_interesse=["natação"])

        result = next_status("comprando", session, INTENT_GREETING, has_order=False)

        self.assertIsNone(result)

    def test_comprando_stays_comprando_even_with_intent_pedido_again(self):
        session = SessionState(item_interesse=["natação"])

        result = next_status("comprando", session, INTENT_PEDIDO, has_order=False)

        self.assertIsNone(result)


class TestNextStatusNeverReachesManualStages(unittest.TestCase):
    """`cliente_ativo`/`cancelado` are admin-only (whatbot/admin.py) — no
    combination of intent/session/has_order may produce them here."""

    def test_intent_pedido_never_yields_cliente_ativo_or_cancelado(self):
        session = SessionState(item_interesse=["natação"])

        result = next_status("interessado", session, INTENT_PEDIDO, has_order=True)

        self.assertEqual(result, "comprando")

    def test_cliente_ativo_never_advances_automatically(self):
        session = SessionState(item_interesse=["natação"])

        result = next_status("cliente_ativo", session, INTENT_PEDIDO, has_order=True)

        self.assertIsNone(result)

    def test_cancelado_never_advances_automatically(self):
        session = SessionState(item_interesse=["natação"])

        result = next_status("cancelado", session, INTENT_PEDIDO, has_order=True)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
