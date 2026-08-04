import os
import unittest
from unittest.mock import patch

from whatbot.admin import handle_admin_message
from whatbot.admin_nlu import (
    is_casual_test_message,
    parse_admin_intent,
    parse_simulate_command,
)
from whatbot.channels import INSTAGRAM, WHATSAPP
from whatbot.config import resolve_simulate_phone
from whatbot.contact_resolver import (
    extract_phone_from_text,
    find_waiting_matches,
    format_disambiguation,
)
from whatbot.db import WaitingContact
from datetime import datetime, timezone

from fakes import FakeClient, FakeDatabase


class TestAdminNlu(unittest.TestCase):
    def test_list_intent(self):
        self.assertEqual(parse_admin_intent("quem ta na fila?").action, "list_queue")

    def test_assume_intent(self):
        intent = parse_admin_intent("assumo a Maria")
        self.assertEqual(intent.action, "assume")
        self.assertIn("maria", intent.query.lower())

    def test_complete_intent(self):
        intent = parse_admin_intent("finalizei com o João")
        self.assertEqual(intent.action, "complete")

    def test_reactivate_intent(self):
        intent = parse_admin_intent("libera o bot para Maria")
        self.assertEqual(intent.action, "reactivate")

    def test_mark_active_client_intent_suffix_phrasing(self):
        intent = parse_admin_intent("marca a Maria como cliente ativo")
        self.assertEqual(intent.action, "mark_active_client")
        self.assertIn("maria", intent.query.lower())

    def test_mark_active_client_intent_prefix_phrasing(self):
        intent = parse_admin_intent("confirma venda da Maria")
        self.assertEqual(intent.action, "mark_active_client")
        self.assertIn("maria", intent.query.lower())

    def test_simulate(self):
        phone, msg = parse_simulate_command("#simular 5511888888888 Olá")
        self.assertEqual(phone, "5511888888888")
        self.assertEqual(msg, "Olá")

    def test_casual_test(self):
        self.assertTrue(is_casual_test_message("Teste"))
        self.assertTrue(is_casual_test_message("olá!"))
        self.assertFalse(is_casual_test_message("quem ta na fila?"))

    def test_resolve_simulate_phone_avoids_business_line(self):
        import os

        os.environ["BUSINESS_PHONE"] = "5511949305094"
        os.environ["DEFAULT_TEST_PHONE"] = "5511949305094"
        self.assertEqual(resolve_simulate_phone(None), "5511999999999")
        self.assertEqual(resolve_simulate_phone("5511888888888"), "5511888888888")


class TestExtractPhoneFromText(unittest.TestCase):
    def test_does_not_match_a_longer_igsid(self):
        """A 17-digit IGSID must never be truncated into a phone-shaped
        match (design.md — Bloqueador 1, requirement "Normalização de
        identidade específica por canal")."""
        self.assertIsNone(extract_phone_from_text("17841400000000000"))

    def test_still_matches_a_real_phone_in_free_text(self):
        self.assertEqual(
            extract_phone_from_text("meu numero eh 11987654321 pode ligar"),
            "11987654321",
        )


class TestContactResolver(unittest.TestCase):
    def test_name_match(self):
        waiting = [
            WaitingContact(
                1, "5511111111111", "Maria Silva", datetime.now(timezone.utc),
                "pedido", 5, 0, None,
            ),
            WaitingContact(
                2, "5511222222222", "Maria Costa", datetime.now(timezone.utc),
                "pedido", 3, 0, None,
            ),
        ]
        matches = find_waiting_matches("maria", waiting)
        self.assertEqual(len(matches), 2)

    def test_phone_query_never_matches_contact_without_phone(self):
        """`phone=None` (non-WhatsApp) never matches a phone-digit query
        (design.md, Decisão 3 — the identified `contact_resolver.py:43` bug)."""
        waiting = [
            WaitingContact(
                1,
                None,
                "Maria IG",
                datetime.now(timezone.utc),
                "pedido",
                5,
                0,
                None,
                canal=INSTAGRAM,
                external_id="551188888888",
                handle="@maria_ig",
            ),
        ]
        matches = find_waiting_matches("551188888888", waiting)
        self.assertEqual(matches, [])

    def test_match_by_handle_when_no_push_name(self):
        """A contact reachable only by channel handle (no `push_name`, the
        realistic shape of a fresh Instagram contact) must still be
        findable — design.md, Bloqueador 2."""
        waiting = [
            WaitingContact(
                1,
                None,
                None,
                datetime.now(timezone.utc),
                "pedido",
                5,
                0,
                None,
                canal=INSTAGRAM,
                external_id="17841400000000000",
                handle="@joana_ig",
            ),
        ]
        matches = find_waiting_matches("joana_ig", waiting)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].contact.handle, "@joana_ig")

    def test_disambiguation_label_tolerates_contact_without_phone(self):
        waiting = WaitingContact(
            1,
            None,
            None,
            datetime.now(timezone.utc),
            "pedido",
            5,
            0,
            None,
            canal=INSTAGRAM,
            external_id="17841400000000000",
            handle="@sem_nome",
        )
        from whatbot.contact_resolver import ContactMatch

        text = format_disambiguation([ContactMatch(waiting, 5)], "assume")
        self.assertIn("@sem_nome", text)

    def test_disambiguation_shows_channel(self):
        """`format_disambiguation` must name the channel next to each
        candidate — the spec requires it for every list of contacts shown
        to the secretariat (channel-queue-visibility)."""
        waiting = WaitingContact(
            1,
            None,
            "Maria IG",
            datetime.now(timezone.utc),
            "pedido",
            5,
            0,
            None,
            canal=INSTAGRAM,
            external_id="17841400000000000",
            handle="@maria_ig",
        )
        from whatbot.contact_resolver import ContactMatch

        text = format_disambiguation([ContactMatch(waiting, 5)], "assume")
        self.assertIn("Instagram", text)


class TestPickFromDisambiguationLegacySession(unittest.TestCase):
    def test_legacy_dict_without_external_id_falls_back_to_phone(self):
        """Admin sessions persisted before this change's deploy (TTL 10 min)
        never had an `external_id` key — must not resolve to `external_id=None`
        (design.md, Importante 4)."""
        from whatbot.contact_resolver import pick_from_disambiguation

        legacy_candidate = {
            "id": 1,
            "phone": "5511888888888",
            "push_name": "Maria",
            "handover_motivo": "pedido",
            "minutes_waiting": 5,
            "prioridade": 0,
            # no "canal"/"external_id"/"handle" keys — pre-migration shape
        }
        picked = pick_from_disambiguation("1", [legacy_candidate])
        self.assertIsNotNone(picked)
        self.assertEqual(picked.external_id, "5511888888888")


class TestReactivateDisambiguationShowsChannel(unittest.TestCase):
    """The `reactivate` disambiguation list (multiple inactive contacts
    matching a name) must name each candidate's channel
    (channel-queue-visibility)."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_two_inactive_contacts_named_maria_show_their_channels(self):
        db = FakeDatabase()
        wa_contact = db.create_contact(phone="5511888888888", push_name="Maria")
        db.contacts[wa_contact.id]["ia_ativa"] = False
        ig_contact = db.create_contact(
            canal=INSTAGRAM,
            external_id="17841400000000000",
            handle="@maria_ig",
            push_name="Maria",
        )
        db.contacts[ig_contact.id]["ia_ativa"] = False
        router = FakeClient(WHATSAPP)

        result = handle_admin_message(
            "5511900000001", "reativar maria", db, router, contact_id=1
        )

        self.assertIn("WhatsApp", result["reply"])
        self.assertIn("Instagram", result["reply"])


class TestMarkActiveClientCommand(unittest.TestCase):
    """`contact-interest-memory`: manual admin command to mark a contact as
    `cliente_ativo`, reusing `search_contacts_for_admin` + the same
    disambiguation flow already covered by `TestReactivateDisambiguationShowsChannel`."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_single_match_marks_the_contact_as_cliente_ativo(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        contact = db.create_contact(phone="5511888888888", push_name="Maria Silva")
        self.assertEqual(contact.status, "novo_lead")

        result = handle_admin_message(
            "5511900000001",
            "marca a Maria Silva como cliente ativo",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        self.assertIn("cliente ativo", result["reply"].lower())
        updated = db.get_contact_by_phone("5511888888888")
        self.assertEqual(updated.status, "cliente_ativo")

    def test_phone_query_marks_the_contact_directly(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Maria Silva")

        result = handle_admin_message(
            "5511900000001",
            "confirma venda do 5511888888888",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        updated = db.get_contact_by_phone("5511888888888")
        self.assertEqual(updated.status, "cliente_ativo")

    def test_two_contacts_named_maria_trigger_disambiguation_then_resolve(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        first = db.create_contact(phone="5511888888888", push_name="Maria Silva")
        second = db.create_contact(phone="5511777777777", push_name="Maria Costa")

        disambiguation = handle_admin_message(
            "5511900000001", "marca a Maria como cliente ativo", db, router, contact_id=1
        )
        self.assertTrue(disambiguation["ok"])
        self.assertIn("Encontrei vários contatos", disambiguation["reply"])

        picked = handle_admin_message(
            "5511900000001", "1", db, router, contact_id=1
        )

        self.assertTrue(picked["ok"])
        self.assertIn("cliente ativo", picked["reply"].lower())
        # `search_contacts_for_admin` orders candidates most-recent-first, so
        # option "1" is Maria Costa (created second, 5511777777777).
        self.assertEqual(
            db.get_contact_by_phone("5511777777777").status, "cliente_ativo"
        )
        # The other Maria is untouched.
        self.assertEqual(
            db.get_contact_by_phone("5511888888888").status, "novo_lead"
        )

    def test_contact_not_found_replies_without_crashing(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)

        result = handle_admin_message(
            "5511900000001", "marca a Fulana como cliente ativo", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("Não encontrei", result["reply"])


if __name__ == "__main__":
    unittest.main()
