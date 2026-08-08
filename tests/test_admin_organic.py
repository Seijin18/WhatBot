import os
import re
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

    def test_pause_intent(self):
        intent = parse_admin_intent("pausa o bot para o João")
        self.assertEqual(intent.action, "pause")
        self.assertIn("joão", intent.query.lower())

    def test_mark_active_client_intent_suffix_phrasing(self):
        intent = parse_admin_intent("marca a Maria como cliente ativo")
        self.assertEqual(intent.action, "mark_active_client")
        self.assertIn("maria", intent.query.lower())

    def test_mark_active_client_intent_prefix_phrasing(self):
        intent = parse_admin_intent("confirma venda da Maria")
        self.assertEqual(intent.action, "mark_active_client")
        self.assertIn("maria", intent.query.lower())

    def test_set_tipo_cliente_intent_empresa_phrasing(self):
        intent = parse_admin_intent("marca a Maria como empresa")
        self.assertEqual(intent.action, "set_tipo_cliente")
        self.assertEqual(intent.tipo_cliente, "b2b")
        self.assertIn("maria", intent.query.lower())

    def test_set_tipo_cliente_intent_pessoa_fisica_phrasing(self):
        intent = parse_admin_intent("marca o João como pessoa física")
        self.assertEqual(intent.action, "set_tipo_cliente")
        self.assertEqual(intent.tipo_cliente, "b2c")
        self.assertIn("joão", intent.query.lower())

    def test_set_tipo_cliente_intent_define_b2b_phrasing(self):
        intent = parse_admin_intent("define Maria como B2B")
        self.assertEqual(intent.action, "set_tipo_cliente")
        self.assertEqual(intent.tipo_cliente, "b2b")
        self.assertIn("maria", intent.query.lower())

    def test_set_tipo_cliente_does_not_collide_with_mark_active_client(self):
        """Both share trigger verbs ("marca"/"marque") — the suffix
        ("como empresa" vs. "como cliente ativo") must be what disambiguates
        the intent, not verb order in `parse_admin_intent`."""
        empresa_intent = parse_admin_intent("marca a Maria como empresa")
        self.assertEqual(empresa_intent.action, "set_tipo_cliente")

        cliente_ativo_intent = parse_admin_intent("marca a Maria como cliente ativo")
        self.assertEqual(cliente_ativo_intent.action, "mark_active_client")

    def test_simulate(self):
        phone, msg = parse_simulate_command("#simular 5511888888888 Olá")
        self.assertEqual(phone, "5511888888888")
        self.assertEqual(msg, "Olá")

    def test_casual_test(self):
        self.assertTrue(is_casual_test_message("Teste"))
        self.assertTrue(is_casual_test_message("olá!"))
        self.assertFalse(is_casual_test_message("quem ta na fila?"))

    def test_ativar_bot_intent(self):
        """`admin-bulk-phone-toggle`: "ativa(r) o bot" is a synonym of
        "reativar", requiring "bot" alongside so it doesn't false-positive
        on unrelated text."""
        intent = parse_admin_intent("ativa o bot 5511999999999")
        self.assertEqual(intent.action, "reactivate")
        self.assertIn("5511999999999", intent.query)

    def test_desativar_bot_does_not_trigger_reactivate(self):
        """Regression: "desativar" must never be mis-parsed as "ativar" —
        no word boundary immediately before "ativa" inside "desativar"."""
        intent = parse_admin_intent("desativa o bot 5511999999999")
        self.assertEqual(intent.action, "pause")

    def test_rename_intent(self):
        intent = parse_admin_intent("renomeia o Pedro para Pedro Silva")
        self.assertEqual(intent.action, "rename")
        self.assertIn("pedro", intent.query.lower())

    def test_delete_contact_intent(self):
        intent = parse_admin_intent("apaga o contato do 5511999999999")
        self.assertEqual(intent.action, "delete_contact")
        self.assertIn("5511999999999", intent.query)

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


class TestSetTipoClienteCommand(unittest.TestCase):
    """`contact-segmentation-b2b-b2c`: manual admin command to label a
    contact as `b2b` (empresa) or `b2c` (pessoa física), reusing
    `search_contacts_for_admin` + the same disambiguation flow already
    covered by `TestMarkActiveClientCommand`/`TestPauseCommand`."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_single_match_marks_the_contact_as_empresa(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        contact = db.create_contact(phone="5511888888888", push_name="Maria Silva")
        self.assertEqual(contact.tipo_cliente, "b2c")

        result = handle_admin_message(
            "5511900000001",
            "marca a Maria Silva como empresa",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        self.assertIn("empresa", result["reply"].lower())
        updated = db.get_contact_by_phone("5511888888888")
        self.assertEqual(updated.tipo_cliente, "b2b")
        # A different axis from `status` — marking `tipo_cliente` must not
        # touch it (regression guard for the shared "marca"/"marque" verbs
        # between this command and `mark_active_client`).
        self.assertEqual(updated.status, "novo_lead")

    def test_define_b2b_phrasing_marks_the_contact_directly(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Maria Silva")

        result = handle_admin_message(
            "5511900000001", "define Maria Silva como B2B", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        updated = db.get_contact_by_phone("5511888888888")
        self.assertEqual(updated.tipo_cliente, "b2b")

    def test_pessoa_fisica_phrasing_switches_an_existing_empresa_back_to_b2c(self):
        # `push_name` intentionally has no diacritic here (unlike the
        # example phrase "João" tested at the NLU layer above): resolution
        # goes through `search_contacts_for_admin`, which folds the *query*
        # to ASCII before matching but does not fold `push_name` — an
        # accented `push_name` would miss (pre-existing bug, shared by
        # `reactivate`/`pause`/`mark_active_client`, out of scope for this
        # change; see also `_SET_TIPO_CLIENTE_B2C_SUFFIX`, which is only
        # responsible for recognizing the "como pessoa física" trigger, not
        # for the name-matching step downstream).
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        contact = db.create_contact(phone="5511888888888", push_name="Joao")
        db.set_contact_tipo_cliente(contact.id, "b2b")

        result = handle_admin_message(
            "5511900000001", "marca o Joao como pessoa física", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("pessoa física", result["reply"].lower())
        updated = db.get_contact_by_phone("5511888888888")
        self.assertEqual(updated.tipo_cliente, "b2c")

    def test_phone_query_marks_the_contact_directly(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Maria Silva")

        result = handle_admin_message(
            "5511900000001",
            "marca 5511888888888 como empresa",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        updated = db.get_contact_by_phone("5511888888888")
        self.assertEqual(updated.tipo_cliente, "b2b")

    def test_two_contacts_named_maria_trigger_disambiguation_then_resolve(self):
        """Regression (bug already caught once for `pause`): the
        disambiguation continuation must actually apply the originally
        requested `tipo_cliente` ("b2b"), not silently drop it — exercised
        end to end, not just asserted on the intermediate `acao` string."""
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        first = db.create_contact(phone="5511888888888", push_name="Maria Silva")
        second = db.create_contact(phone="5511777777777", push_name="Maria Costa")

        disambiguation = handle_admin_message(
            "5511900000001", "marca a Maria como empresa", db, router, contact_id=1
        )
        self.assertTrue(disambiguation["ok"])
        self.assertIn("Encontrei vários contatos", disambiguation["reply"])
        # Scenario "Nome ambíguo desambigua antes de alterar" — nothing
        # changes until the admin answers.
        self.assertEqual(db.get_contact_by_phone("5511888888888").tipo_cliente, "b2c")
        self.assertEqual(db.get_contact_by_phone("5511777777777").tipo_cliente, "b2c")

        picked = handle_admin_message(
            "5511900000001", "1", db, router, contact_id=1
        )

        self.assertTrue(picked["ok"])
        self.assertIn("empresa", picked["reply"].lower())
        # `search_contacts_for_admin` orders candidates most-recent-first, so
        # option "1" is Maria Costa (created second, 5511777777777).
        self.assertEqual(
            db.get_contact_by_phone("5511777777777").tipo_cliente, "b2b"
        )
        # The other Maria is untouched.
        self.assertEqual(
            db.get_contact_by_phone("5511888888888").tipo_cliente, "b2c"
        )

    def test_contact_not_found_replies_without_crashing(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)

        result = handle_admin_message(
            "5511900000001", "marca a Fulana como empresa", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("Não encontrei", result["reply"])

    def test_confirmation_does_not_suggest_a_next_command(self):
        """Design decision for this command (unlike `pause`'s confirmation):
        no obvious single "inverse" command exists, so the reply must not
        invent one — a made-up suggestion risks the exact bug already caught
        for `pause` (a phrase that silently fails to resolve through
        `search_contacts_for_admin`'s untokenized substring match)."""
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Maria Silva")

        result = handle_admin_message(
            "5511900000001",
            "marca a Maria Silva como empresa",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        self.assertNotIn("Envie", result["reply"])


class TestPausarBotDb(unittest.TestCase):
    """`Database.pausar_bot` (admin-bot-pause), exercised through
    `FakeDatabase.pausar_bot`, which mirrors the same contract."""

    def test_deactivates_ia_ativa_and_returns_true_for_existing_contact(self):
        db = FakeDatabase()
        contact = db.create_contact(phone="5511888888888", push_name="Pedro")

        self.assertTrue(db.pausar_bot("5511888888888"))
        self.assertFalse(db.contacts[contact.id]["ia_ativa"])

    def test_returns_false_for_nonexistent_contact(self):
        db = FakeDatabase()

        self.assertFalse(db.pausar_bot("5511000000000"))

    def test_does_not_set_bot_resume_at(self):
        """Decisão 2 (design.md): a manual pause is indefinite — it must
        never set `bot_resume_at`, or `process_auto_reactivations()` would
        pick it up on a schedule."""
        db = FakeDatabase()
        contact = db.create_contact(phone="5511888888888", push_name="Pedro")

        db.pausar_bot("5511888888888")

        self.assertIsNone(db.contacts[contact.id]["bot_resume_at"])


class TestPauseCommand(unittest.TestCase):
    """`admin-bot-pause`: admin command to pause the bot for a contact
    outside the handover queue, reusing the same resolution/disambiguation
    shape as `TestReactivateDisambiguationShowsChannel` /
    `TestMarkActiveClientCommand`."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_single_match_pauses_the_contact_directly(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        contact = db.create_contact(phone="5511888888888", push_name="Pedro")
        self.assertTrue(contact.ia_ativa)

        result = handle_admin_message(
            "5511900000001", "pausa o bot para o Pedro", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("pausado", result["reply"].lower())
        self.assertFalse(db.get_contact_by_phone("5511888888888").ia_ativa)

    def test_phone_query_pauses_the_contact_directly(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro")

        result = handle_admin_message(
            "5511900000001", "desativa o bot 5511888888888", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertFalse(db.get_contact_by_phone("5511888888888").ia_ativa)

    def test_two_active_contacts_named_maria_trigger_disambiguation_then_resolve(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Maria Silva")
        db.create_contact(phone="5511777777777", push_name="Maria Costa")

        disambiguation = handle_admin_message(
            "5511900000001", "pausa o bot para a Maria", db, router, contact_id=1
        )
        self.assertTrue(disambiguation["ok"])
        self.assertIn("Encontrei vários contatos", disambiguation["reply"])

        picked = handle_admin_message("5511900000001", "1", db, router, contact_id=1)

        self.assertTrue(picked["ok"])
        self.assertIn("pausado", picked["reply"].lower())
        # `search_contacts_for_admin` orders candidates most-recent-first, so
        # option "1" is Maria Costa (created second, 5511777777777).
        self.assertFalse(db.get_contact_by_phone("5511777777777").ia_ativa)
        # The other Maria is untouched.
        self.assertTrue(db.get_contact_by_phone("5511888888888").ia_ativa)

    def test_already_paused_contact_is_not_offered_and_replies_without_error(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(
            phone="5511888888888", push_name="Pedro", ia_ativa=False
        )

        result = handle_admin_message(
            "5511900000001", "pausa o bot para o Pedro", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("já está com o bot pausado", result["reply"])

    def test_contact_not_found_replies_without_crashing(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)

        result = handle_admin_message(
            "5511900000001", "pausa o bot para a Fulana", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("Não encontrei", result["reply"])

    def test_paused_contact_is_not_picked_up_by_auto_reactivations(self):
        """Scenario "Contato pausado não é reativado automaticamente" —
        `bot_resume_at` stays `NULL`, so the sweep never touches it."""
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro")

        handle_admin_message(
            "5511900000001", "pausa o bot para o Pedro", db, router, contact_id=1
        )
        self.assertFalse(db.get_contact_by_phone("5511888888888").ia_ativa)

        reactivated = db.process_auto_reactivations()

        self.assertEqual(reactivated, [])
        self.assertFalse(db.get_contact_by_phone("5511888888888").ia_ativa)

    def test_existing_reactivate_command_still_resumes_a_manually_paused_contact(self):
        """Scenario "Comando de reativação existente também retoma pausa
        manual" — `libera o bot` (`reactivate`, untouched by this change)
        reactivates a contact paused by the new `pause` command, because
        both share the same `ia_ativa` field."""
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro")

        handle_admin_message(
            "5511900000001", "pausa o bot para o Pedro", db, router, contact_id=1
        )
        self.assertFalse(db.get_contact_by_phone("5511888888888").ia_ativa)

        # "reativar" phrasing rather than "libera o bot para o Pedro": the
        # latter's "para" is not swallowed by `_REACTIVATE` (pre-existing,
        # out of this change's scope — `_REACTIVATE` must not be modified),
        # so `search_contacts_for_admin`'s raw substring match would miss.
        result = handle_admin_message(
            "5511900000001", "reativar Pedro", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertTrue(db.get_contact_by_phone("5511888888888").ia_ativa)

    def test_confirmation_message_suggests_a_command_that_actually_reactivates(self):
        """Regression (critic finding): the *exact* phrase suggested by the
        pause confirmation message must work when the target was resolved
        by name (the common case), not just by phone. Extracts the
        suggested command straight out of the reply text and executes it
        verbatim — a literal "libera o bot para {label}" alternative would
        NOT have caught this, since `_REACTIVATE` doesn't swallow a
        trailing "para o/a" and `search_contacts_for_admin` matches by raw
        substring."""
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro")

        pause_result = handle_admin_message(
            "5511900000001", "pausa o bot para o Pedro", db, router, contact_id=1
        )
        self.assertFalse(db.get_contact_by_phone("5511888888888").ia_ativa)

        match = re.search(r"Envie \*(.+?)\*", pause_result["reply"])
        self.assertIsNotNone(match, pause_result["reply"])
        suggested_command = match.group(1)

        result = handle_admin_message(
            "5511900000001", suggested_command, db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertTrue(db.get_contact_by_phone("5511888888888").ia_ativa)


class TestCompleteReactivatesBotImmediately(unittest.TestCase):
    """`admin-attend-keeps-bot-active`: finalizar um atendimento (item
    único ou em lote) não deixa mais o bot desligado por
    `AUTO_REACTIVATE_HOURS` — reativa `ia_ativa` na hora, sem
    `bot_resume_at`."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_complete_single_item_reactivates_bot_immediately(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        contact = db.create_contact(phone="5511888888888", push_name="Pedro")
        db.enroll_handover(contact.id, motivo="pedido_do_cliente")

        result = handle_admin_message(
            "5511900000001", "atendi o Pedro", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertNotIn("h*", result["reply"])
        updated = db.get_contact_by_phone("5511888888888")
        self.assertTrue(updated.ia_ativa)
        self.assertIsNone(db.contacts[contact.id]["bot_resume_at"])

    def test_complete_all_reactivates_every_contact_immediately(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        pedro = db.create_contact(phone="5511888888888", push_name="Pedro")
        maria = db.create_contact(phone="5511777777777", push_name="Maria")
        db.enroll_handover(pedro.id, motivo="pedido_do_cliente")
        db.enroll_handover(maria.id, motivo="pedido_do_cliente")

        result = handle_admin_message(
            "5511900000001", "atender todos", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertTrue(db.get_contact_by_phone("5511888888888").ia_ativa)
        self.assertTrue(db.get_contact_by_phone("5511777777777").ia_ativa)
        self.assertIsNone(db.contacts[pedro.id]["bot_resume_at"])
        self.assertIsNone(db.contacts[maria.id]["bot_resume_at"])


class TestReactivateAccentFold(unittest.TestCase):
    """`search_contacts_for_admin` must fold accents on both sides of the
    comparison — the admin's typed query *and* the stored `push_name` —
    not just the query (pre-existing bug, found and documented during
    contact-segmentation-b2b-b2c, confirmed pre-existing by `git log -p`).
    Without this, "reativar joao" silently fails to find a contact saved
    as "João" instead of erroring."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_accented_stored_name_found_by_unaccented_query(self):
        db = FakeDatabase()
        contact = db.create_contact(phone="5511888888888", push_name="João")
        db.contacts[contact.id]["ia_ativa"] = False
        router = FakeClient(WHATSAPP)

        result = handle_admin_message(
            "5511900000001", "reativar joao", db, router, contact_id=1
        )

        self.assertIn("Bot reativado", result["reply"])
        self.assertTrue(db.contacts[contact.id]["ia_ativa"])

    def test_unaccented_stored_name_found_by_accented_query(self):
        db = FakeDatabase()
        contact = db.create_contact(phone="5511888888888", push_name="Joao")
        db.contacts[contact.id]["ia_ativa"] = False
        router = FakeClient(WHATSAPP)

        result = handle_admin_message(
            "5511900000001", "reativar joão", db, router, contact_id=1
        )

        self.assertIn("Bot reativado", result["reply"])
        self.assertTrue(db.contacts[contact.id]["ia_ativa"])


class TestBulkPhoneToggleCommand(unittest.TestCase):
    """`admin-bulk-phone-toggle`: ativar/desativar por telefone único ou
    lista, com fallback idempotente."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_single_phone_already_paused_is_idempotent(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro", ia_ativa=False)

        result = handle_admin_message(
            "5511900000001", "desativa o bot 5511888888888", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("já está com o bot pausado", result["reply"])
        self.assertFalse(db.get_contact_by_phone("5511888888888").ia_ativa)

    def test_single_phone_already_active_on_reactivate_is_idempotent(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro", ia_ativa=True)

        result = handle_admin_message(
            "5511900000001", "ativa o bot 5511888888888", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("já está ativo", result["reply"])
        self.assertTrue(db.get_contact_by_phone("5511888888888").ia_ativa)

    def test_list_with_mixed_states_for_pause(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro", ia_ativa=True)
        db.create_contact(phone="5511777777777", push_name="Maria", ia_ativa=False)

        result = handle_admin_message(
            "5511900000001",
            "desativa o bot 5511888888888, 5511777777777",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        self.assertIn("5511888888888", result["reply"])
        self.assertIn("5511777777777", result["reply"])
        self.assertFalse(db.get_contact_by_phone("5511888888888").ia_ativa)
        self.assertFalse(db.get_contact_by_phone("5511777777777").ia_ativa)

    def test_list_with_mixed_states_for_reactivate(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro", ia_ativa=False)
        db.create_contact(phone="5511777777777", push_name="Maria", ia_ativa=True)

        result = handle_admin_message(
            "5511900000001",
            "ativa o bot 5511888888888, 5511777777777",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        self.assertIn("5511888888888", result["reply"])
        self.assertIn("5511777777777", result["reply"])
        self.assertTrue(db.get_contact_by_phone("5511888888888").ia_ativa)
        self.assertTrue(db.get_contact_by_phone("5511777777777").ia_ativa)

    def test_list_with_missing_number_does_not_crash_and_does_not_offer_creation(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro", ia_ativa=True)

        result = handle_admin_message(
            "5511900000001",
            "desativa o bot 5511888888888, 5511777777777",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        self.assertIn("Não encontrado", result["reply"])
        self.assertIn("5511777777777", result["reply"])
        # Não dispara o fluxo de criação (só para telefone único).
        self.assertIsNone(db.get_admin_sessao("5511900000001"))

    def test_duplicate_number_in_list_is_deduplicated(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro", ia_ativa=True)

        result = handle_admin_message(
            "5511900000001",
            "desativa o bot 5511888888888, 5511888888888",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"].count("5511888888888"), 1)

    def test_non_numeric_segment_is_reported_as_unrecognized(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro", ia_ativa=True)

        result = handle_admin_message(
            "5511900000001",
            "desativa o bot 5511888888888, xyz",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        self.assertIn("Não reconhecido", result["reply"])


class TestContactCreationFlow(unittest.TestCase):
    """`admin-bulk-phone-toggle`, Parte B: telefone único não encontrado
    oferece cadastro como novo contato."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unknown_single_phone_asks_for_a_name(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)

        result = handle_admin_message(
            "5511900000001", "ativa o bot 5511888888888", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("Não encontrei", result["reply"])
        self.assertIsNone(db.get_contact_by_phone("5511888888888"))

    def test_answering_with_a_name_creates_contact_in_the_requested_state(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)

        handle_admin_message(
            "5511900000001", "desativa o bot 5511888888888", db, router, contact_id=1
        )
        result = handle_admin_message(
            "5511900000001", "Pedro Silva", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("Pedro Silva", result["reply"])
        contact = db.get_contact_by_phone("5511888888888")
        self.assertIsNotNone(contact)
        self.assertEqual(contact.push_name, "Pedro Silva")
        self.assertFalse(contact.ia_ativa)

    def test_answering_nao_cancels_without_creating(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)

        handle_admin_message(
            "5511900000001", "ativa o bot 5511888888888", db, router, contact_id=1
        )
        result = handle_admin_message(
            "5511900000001", "não", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIsNone(db.get_contact_by_phone("5511888888888"))


class TestRenameCommand(unittest.TestCase):
    """`admin-bulk-phone-toggle`, Parte C."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rename_by_name(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        contact = db.create_contact(phone="5511888888888", push_name="Pedro")

        result = handle_admin_message(
            "5511900000001",
            "renomeia o Pedro para Pedro Silva",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        self.assertIn("Pedro Silva", result["reply"])
        self.assertEqual(
            db.get_contact_by_phone("5511888888888").push_name, "Pedro Silva"
        )

    def test_rename_by_phone(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro")

        result = handle_admin_message(
            "5511900000001",
            "renomeia 5511888888888 para Pedro Silva",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            db.get_contact_by_phone("5511888888888").push_name, "Pedro Silva"
        )

    def test_rename_with_disambiguation(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Maria Silva")
        db.create_contact(phone="5511777777777", push_name="Maria Costa")

        disambiguation = handle_admin_message(
            "5511900000001",
            "renomeia a Maria para Maria Nova",
            db,
            router,
            contact_id=1,
        )
        self.assertTrue(disambiguation["ok"])
        self.assertIn("Encontrei vários contatos", disambiguation["reply"])

        picked = handle_admin_message("5511900000001", "1", db, router, contact_id=1)

        self.assertTrue(picked["ok"])
        self.assertIn("Maria Nova", picked["reply"])
        # Most-recent-first: option "1" is Maria Costa (5511777777777).
        self.assertEqual(
            db.get_contact_by_phone("5511777777777").push_name, "Maria Nova"
        )
        self.assertEqual(
            db.get_contact_by_phone("5511888888888").push_name, "Maria Silva"
        )

    def test_missing_para_returns_usage_without_mutating(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro")

        result = handle_admin_message(
            "5511900000001", "renomeia o Pedro", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("Envie assim", result["reply"])
        self.assertEqual(
            db.get_contact_by_phone("5511888888888").push_name, "Pedro"
        )

    def test_contact_not_found(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)

        result = handle_admin_message(
            "5511900000001",
            "renomeia o Fulano para Novo Nome",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        self.assertIn("Não encontrei", result["reply"])


class TestDeleteContactCommand(unittest.TestCase):
    """`admin-bulk-phone-toggle`, Parte D."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_single_match_asks_for_confirmation_without_deleting(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro")

        result = handle_admin_message(
            "5511900000001",
            "apaga o contato do Pedro",
            db,
            router,
            contact_id=1,
        )

        self.assertTrue(result["ok"])
        self.assertIn("Tem certeza", result["reply"])
        self.assertIsNotNone(db.get_contact_by_phone("5511888888888"))

    def test_confirming_with_sim_deletes(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro")

        handle_admin_message(
            "5511900000001", "apaga o contato do Pedro", db, router, contact_id=1
        )
        result = handle_admin_message(
            "5511900000001", "sim", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("apagado", result["reply"])
        self.assertIsNone(db.get_contact_by_phone("5511888888888"))

    def test_any_other_reply_cancels_without_deleting(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Pedro")

        handle_admin_message(
            "5511900000001", "apaga o contato do Pedro", db, router, contact_id=1
        )
        result = handle_admin_message(
            "5511900000001", "opa não", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIsNotNone(db.get_contact_by_phone("5511888888888"))

    def test_disambiguation_then_confirmation_deletes_only_the_chosen_one(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        db.create_contact(phone="5511888888888", push_name="Maria Silva")
        db.create_contact(phone="5511777777777", push_name="Maria Costa")

        disambiguation = handle_admin_message(
            "5511900000001", "apaga o contato da Maria", db, router, contact_id=1
        )
        self.assertIn("Encontrei vários contatos", disambiguation["reply"])

        confirmation_prompt = handle_admin_message(
            "5511900000001", "1", db, router, contact_id=1
        )
        self.assertIn("Tem certeza", confirmation_prompt["reply"])

        result = handle_admin_message(
            "5511900000001", "sim", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        # Most-recent-first: option "1" is Maria Costa (5511777777777).
        self.assertIsNone(db.get_contact_by_phone("5511777777777"))
        self.assertIsNotNone(db.get_contact_by_phone("5511888888888"))

    def test_contact_not_found(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)

        result = handle_admin_message(
            "5511900000001", "apaga o contato do Fulano", db, router, contact_id=1
        )

        self.assertTrue(result["ok"])
        self.assertIn("Não encontrei", result["reply"])


if __name__ == "__main__":
    unittest.main()
