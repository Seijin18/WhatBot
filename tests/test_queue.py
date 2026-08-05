import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from whatbot.channels import INSTAGRAM, WHATSAPP
from whatbot.priority import calcular_prioridade_handover, prioridade_label
from whatbot.queue import (
    build_contact_summary,
    build_daily_summary,
    format_waiting_list,
    handle_staff_outgoing_message,
    normalize_phone,
    notify_assumption,
    process_new_handover,
)
from whatbot.db import WaitingContact
from whatbot.session_state import SessionState
from whatbot.webhook import parse_outgoing_staff_message

from fakes import FakeClient, FakeDatabase


class TestPriority(unittest.TestCase):
    def test_alta_prioridade_matricula(self):
        self.assertEqual(calcular_prioridade_handover("Quero fazer matrícula de judô"), 1)

    def test_prioridade_normal(self):
        self.assertEqual(calcular_prioridade_handover("Qual o horário?"), 0)

    def test_prioridade_label(self):
        self.assertEqual(prioridade_label(1), "🔥 ALTA")

    def test_order_present_forces_priority_1_regardless_of_text(self):
        """catalog-order-capture, Decisão 3: um pedido do catálogo força
        prioridade 1 mesmo com um texto sintético neutro, independente de
        `items_identifiable`."""
        identifiable_order = {"order_id": "ORD-1", "items_identifiable": True}
        unidentifiable_order = {"order_id": "ORD-2", "items_identifiable": False}

        self.assertEqual(
            calcular_prioridade_handover(
                "[pedido do catálogo] 2 item(ns)", order=identifiable_order
            ),
            1,
        )
        self.assertEqual(
            calcular_prioridade_handover(
                "[pedido do catálogo] itens não identificados",
                order=unidentifiable_order,
            ),
            1,
        )

    def test_no_order_falls_back_to_keyword_detection(self):
        self.assertEqual(
            calcular_prioridade_handover("Qual o horário?", order=None), 0
        )


class TestOutgoingWebhook(unittest.TestCase):
    def test_parse_outgoing_staff_message(self):
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "5511999999999@s.whatsapp.net",
                    "fromMe": True,
                    "id": "ABC",
                },
                "message": {"conversation": "Olá, sou da secretaria"},
            },
        }
        parsed = parse_outgoing_staff_message(payload)
        self.assertEqual(parsed["to_number"], "5511999999999")
        self.assertTrue(parsed["from_me"])


class TestQueueFormat(unittest.TestCase):
    def test_format_includes_priority_and_assumido(self):
        contacts = [
            WaitingContact(
                id=1,
                phone="5511888888888",
                push_name="Maria",
                handover_at=datetime.now(timezone.utc),
                handover_motivo="pedido_do_cliente",
                minutes_waiting=5,
                prioridade=1,
                assumido_por="5511777777777",
            )
        ]
        text = format_waiting_list(contacts, "Fila")
        self.assertIn("ALTA", text)
        self.assertIn("5511777777777", text)

    def test_format_tolerates_contact_without_phone(self):
        """Non-WhatsApp contacts have `phone=None` (design.md, Decisão 3)."""
        contacts = [
            WaitingContact(
                id=1,
                phone=None,
                push_name="Maria IG",
                handover_at=datetime.now(timezone.utc),
                handover_motivo="pedido_do_cliente",
                minutes_waiting=2,
                prioridade=0,
                assumido_por=None,
                canal=INSTAGRAM,
                external_id="17841400000000000",
                handle="@maria_ig",
            )
        ]
        text = format_waiting_list(contacts, "Fila")
        self.assertIn("Maria IG", text)
        # Identity chip uses the unified precedence (handle -> external_id,
        # see whatbot/db.py:resolve_label) — handle wins here.
        self.assertIn("@maria_ig", text)

    def test_format_shows_whatsapp_channel_label(self):
        """`format_waiting_list` (the `#fila` listing) must name the channel
        next to each contact, not just the identity chip
        (channel-queue-visibility)."""
        contacts = [
            WaitingContact(
                id=1,
                phone="5511888888888",
                push_name="Maria",
                handover_at=datetime.now(timezone.utc),
                handover_motivo="pedido_do_cliente",
                minutes_waiting=5,
                prioridade=0,
                assumido_por=None,
                canal=WHATSAPP,
            )
        ]
        text = format_waiting_list(contacts, "Fila")
        self.assertIn("WhatsApp", text)

    def test_format_shows_instagram_channel_label(self):
        contacts = [
            WaitingContact(
                id=1,
                phone=None,
                push_name="Maria IG",
                handover_at=datetime.now(timezone.utc),
                handover_motivo="pedido_do_cliente",
                minutes_waiting=2,
                prioridade=0,
                assumido_por=None,
                canal=INSTAGRAM,
                external_id="17841400000000000",
                handle="@maria_ig",
            )
        ]
        text = format_waiting_list(contacts, "Fila")
        self.assertIn("Instagram", text)

    def test_format_shows_the_response_deadline_for_instagram(self):
        """IMPORTANTE 4 do critic: `format_waiting_list` alimenta tanto a
        notificação de lote quanto a de espera prolongada
        (`check_long_wait_notifications`) e o comando "quem está na fila?" —
        a espera prolongada é justamente onde o prazo mais importa."""
        now = datetime.now(timezone.utc)
        contacts = [
            WaitingContact(
                id=1,
                phone=None,
                push_name="Maria IG",
                handover_at=now,
                handover_motivo="pedido_do_cliente",
                minutes_waiting=2,
                prioridade=0,
                assumido_por=None,
                canal=INSTAGRAM,
                external_id="17841400000000000",
                handle="@maria_ig",
                last_inbound_at=now - timedelta(hours=1),
            )
        ]
        text = format_waiting_list(contacts, "Fila")
        self.assertIn("Prazo de resposta", text)
        self.assertIn("24h", text)

    def test_format_omits_the_deadline_for_whatsapp(self):
        contacts = [
            WaitingContact(
                id=1,
                phone="5511888888888",
                push_name="Maria",
                handover_at=datetime.now(timezone.utc),
                handover_motivo="pedido_do_cliente",
                minutes_waiting=5,
                prioridade=0,
                assumido_por=None,
                canal=WHATSAPP,
            )
        ]
        text = format_waiting_list(contacts, "Fila")
        self.assertNotIn("Prazo de resposta", text)


class TestNotifyAssumptionShowsChannel(unittest.TestCase):
    """`notify_assumption` ("atendimento assumido") must name the channel
    (channel-queue-visibility)."""

    def setUp(self):
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001,5511900000002"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_whatsapp_contact_shows_whatsapp(self):
        contact = WaitingContact(
            id=1,
            phone="5511888888888",
            push_name="Maria",
            handover_at=datetime.now(timezone.utc),
            handover_motivo="pedido_do_cliente",
            minutes_waiting=5,
            prioridade=0,
            assumido_por="5511900000001",
            canal=WHATSAPP,
        )
        router = FakeClient(WHATSAPP)

        notify_assumption(router, "5511900000001", contact)

        self.assertTrue(router.sent)
        self.assertIn("WhatsApp", router.sent[0]["text"])

    def test_instagram_contact_shows_instagram(self):
        contact = WaitingContact(
            id=1,
            phone=None,
            push_name="Maria IG",
            handover_at=datetime.now(timezone.utc),
            handover_motivo="pedido_do_cliente",
            minutes_waiting=2,
            prioridade=0,
            assumido_por="5511900000001",
            canal=INSTAGRAM,
            external_id="17841400000000000",
            handle="@maria_ig",
        )
        router = FakeClient(WHATSAPP)

        notify_assumption(router, "5511900000001", contact)

        self.assertTrue(router.sent)
        self.assertIn("Instagram", router.sent[0]["text"])


class TestBuildDailySummaryShowsChannelBreakdown(unittest.TestCase):
    """`build_daily_summary` ("Ainda na fila") must break the still-waiting
    count down by channel (channel-queue-visibility)."""

    def test_summary_lists_waiting_contacts_by_channel(self):
        db = FakeDatabase()
        wa_contact = db.create_contact(phone="5511888888888", push_name="Maria")
        db.enroll_handover(wa_contact.id, motivo="pedido_do_cliente")
        ig_contact = db.create_contact(
            canal=INSTAGRAM, external_id="17841400000000000", handle="@maria_ig"
        )
        db.enroll_handover(ig_contact.id, motivo="pedido_do_cliente")

        summary = build_daily_summary(db)

        self.assertIn("Ainda na fila", summary)
        self.assertIn("WhatsApp: 1", summary)
        self.assertIn("Instagram: 1", summary)


class TestProcessNewHandoverShowsChannel(unittest.TestCase):
    """Immediate handover notification names the channel, not just the label
    (channel-queue-visibility)."""

    def setUp(self):
        self.db = FakeDatabase()
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_whatsapp_contact_shows_whatsapp(self):
        contact = self.db.create_contact(phone="5511888888888", push_name="Maria")
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")
        waiting = self.db.get_contact_waiting("5511888888888")
        router = FakeClient(WHATSAPP)

        process_new_handover(self.db, router, contact=waiting)

        self.assertTrue(router.sent)
        self.assertIn("WhatsApp", router.sent[0]["text"])

    def test_instagram_contact_shows_instagram(self):
        contact = self.db.create_contact(
            canal=INSTAGRAM, external_id="17841400000000000", handle="@maria_ig"
        )
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")
        waiting = self.db.get_contact_waiting(
            "17841400000000000", canal=INSTAGRAM
        )
        router = FakeClient(WHATSAPP)

        process_new_handover(self.db, router, contact=waiting)

        self.assertTrue(router.sent)
        self.assertIn("Instagram", router.sent[0]["text"])
        self.assertIn("@maria_ig", router.sent[0]["text"])


class TestBuildContactSummary(unittest.TestCase):
    """handover-summary-for-agent: `build_contact_summary()` is the
    deterministic (no-LLM, design.md Decisão 1) resumo shown to the admin."""

    def _waiting(self, **overrides) -> WaitingContact:
        base = dict(
            id=1,
            phone="5511888888888",
            push_name="Maria",
            handover_at=datetime.now(timezone.utc),
            handover_motivo="pedido_do_cliente",
            minutes_waiting=1,
            status="novo_lead",
            session_state={},
        )
        base.update(overrides)
        return WaitingContact(**base)

    def test_no_signal_at_all_summary_is_empty(self):
        """Requirement "Notificação de handover inclui resumo do contato",
        Scenario "Contato sem nenhum sinal de interesse": with nothing
        resolved (no stage, no interest, no order, no history), the summary
        is an empty string — callers must skip the section entirely rather
        than render a blank header."""
        contact = self._waiting(status=None, session_state=None)

        summary = build_contact_summary(contact, None)

        self.assertEqual(summary, "")

    def test_default_stage_only_is_a_short_one_liner(self):
        """A brand-new lead (`novo_lead`, no interest registered yet) still
        gets a real, short stage line — not an empty/broken section (tasks.md
        3.1: "curto/vazio, sem quebrar formatação")."""
        contact = self._waiting(status="novo_lead", session_state={})

        summary = build_contact_summary(contact, {})

        self.assertEqual(summary, "Estágio: novo lead")

    def test_interest_and_stage_are_included(self):
        contact = self._waiting(status="interessado")

        summary = build_contact_summary(
            contact, SessionState(item_interesse=["natação"])
        )

        self.assertIn("Estágio: interessado", summary)
        self.assertIn("Interesse: natação", summary)

    def test_accepts_a_raw_session_state_dict(self):
        """`session_state` may arrive as the raw dict straight out of the
        `contatos.session_state` JSONB column (`WaitingContact.session_state`),
        not necessarily an already-deserialized `SessionState`."""
        contact = self._waiting(status="interessado")

        summary = build_contact_summary(
            contact, {"item_interesse": ["natação"], "topico_atual": "precos"}
        )

        self.assertIn("Interesse: natação", summary)

    def test_identifiable_order_lists_resolved_items(self):
        """Android order: `items_identifiable=True` and the caller already
        resolved names/prices via `Database.resolve_catalog_items`, prices
        in pt-BR formatting (comma decimal separator)."""
        contact = self._waiting()
        order = {
            "order_id": "ORD-1",
            "item_count": 2,
            "order_title": "Pedido de camisetas",
            "items_identifiable": True,
            "items": [
                {"productId": "PROD-1", "quantity": 1},
                {"productId": "PROD-2", "quantity": 1},
            ],
            "resolved_items": [
                {"product_id": "PROD-1", "nome": "Camiseta", "preco": 49.9, "quantity": 1},
                {"product_id": "PROD-2", "nome": "Boné", "preco": 29.9, "quantity": 1},
            ],
        }

        summary = build_contact_summary(contact, {}, last_order=order)

        self.assertIn("Pedido: Camiseta (R$ 49,90); Boné (R$ 29,90)", summary)

    def test_identifiable_order_shows_the_ordered_quantity(self):
        """critic finding: a 3-unit order must not read the same as a
        1-unit order — `quantity` (already captured by
        `catalog-order-capture`, merged back in by `_resolve_order_for_summary`)
        must show up in the summary, not just the resolved name/price."""
        contact = self._waiting()
        order = {
            "order_id": "ORD-1",
            "item_count": 4,
            "order_title": "Pedido de camisetas",
            "items_identifiable": True,
            "items": [
                {"productId": "PROD-1", "quantity": 1},
                {"productId": "PROD-2", "quantity": 3},
            ],
            "resolved_items": [
                {"product_id": "PROD-1", "nome": "Camiseta", "preco": 49.9, "quantity": 1},
                {"product_id": "PROD-2", "nome": "Boné", "preco": 29.9, "quantity": 3},
            ],
        }

        summary = build_contact_summary(contact, {}, last_order=order)

        # Single unit: no "x1" noise. Multiple units: quantity shown, and the
        # price is explicitly "per unit" (never ambiguous about totals).
        self.assertIn("Camiseta (R$ 49,90)", summary)
        self.assertIn("Boné x3 (R$ 29,90 cada)", summary)

    def test_partial_resolution_lists_known_items_and_flags_the_rest(self):
        """design.md Decisão 2: "cache vazio para um productId ESPECÍFICO"
        degrades only that item, not the whole order — when the local
        catalog cache only resolves SOME of the productIds, the summary must
        list what it knows and explicitly flag how many it couldn't
        identify, never silently show a shorter order than reality."""
        contact = self._waiting()
        order = {
            "order_id": "ORD-3",
            "item_count": 3,
            "order_title": "Pedido misto",
            "items_identifiable": True,
            "items": [
                {"productId": "PROD-1", "quantity": 1},
                {"productId": "PROD-2", "quantity": 1},
                {"productId": "PROD-UNKNOWN", "quantity": 1},
            ],
            # Only PROD-1 was in the local catalog cache.
            "resolved_items": [
                {"product_id": "PROD-1", "nome": "Camiseta", "preco": 49.9, "quantity": 1},
            ],
        }

        summary = build_contact_summary(contact, {}, last_order=order)

        self.assertIn("Camiseta", summary)
        self.assertIn("+ 2 item(ns) não identificado(s)", summary)
        # Must not silently look like a complete, fully-known 1-item order.
        self.assertNotIn("Boné", summary)

    def test_identifiable_order_falls_back_to_raw_capture_without_resolution(self):
        """design.md Decisão 2: without `catalog-product-sync` resolving
        (empty cache/`resolved_items`), degrades to the raw
        `order_title`/`item_count` `catalog-order-capture` already
        captured — never fails, never stays silent."""
        contact = self._waiting()
        order = {
            "order_id": "ORD-1",
            "item_count": 2,
            "order_title": "Pedido de camisetas",
            "items_identifiable": True,
            "resolved_items": [],
        }

        summary = build_contact_summary(contact, {}, last_order=order)

        self.assertIn("Pedido: Pedido de camisetas (2 item(ns))", summary)

    def test_unidentifiable_order_shows_explicit_warning(self):
        """iOS order: `items_identifiable=False` — the attendant must be
        told explicitly to confirm with the customer."""
        contact = self._waiting()
        order = {
            "order_id": "ORD-2",
            "item_count": 3,
            "order_title": "whatbot",
            "items_identifiable": False,
        }

        summary = build_contact_summary(contact, {}, last_order=order)

        self.assertIn("itens não identificados", summary)
        self.assertIn("confirmar com o cliente", summary)


class TestProcessNewHandoverIncludesSummary(unittest.TestCase):
    """handover-summary-for-agent: the immediate "🆕 Novo na fila"
    notification includes `build_contact_summary`, below the existing
    data (tasks.md 2.1)."""

    def setUp(self):
        self.db = FakeDatabase()
        patcher = patch.dict(os.environ, {"ADMIN_NOTIFY_PHONES": "5511900000001"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_includes_interest_and_stage(self):
        contact = self.db.create_contact(phone="5511888888888", push_name="Maria")
        self.db.update_contact_session_state(
            contact.id, {"item_interesse": ["natação"]}
        )
        self.db.set_contact_status(contact.id, "interessado")
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")
        waiting = self.db.get_contact_waiting("5511888888888")
        router = FakeClient(WHATSAPP)

        process_new_handover(self.db, router, contact=waiting)

        self.assertTrue(router.sent)
        text = router.sent[0]["text"]
        self.assertIn("Estágio: interessado", text)
        self.assertIn("Interesse: natação", text)

    def test_identifiable_order_resolves_via_catalog_product_sync(self):
        self.db.upsert_catalog_products(
            [
                {"product_id": "PROD-1", "nome": "Camiseta", "preco": 49.9, "disponivel": True},
                {"product_id": "PROD-2", "nome": "Boné", "preco": 29.9, "disponivel": True},
            ]
        )
        contact = self.db.create_contact(phone="5511888888888", push_name="Maria")
        self.db.set_contact_status(contact.id, "comprando")
        self.db.enroll_handover(contact.id, motivo="pedido_catalogo", prioridade=1)
        waiting = self.db.get_contact_waiting("5511888888888")
        router = FakeClient(WHATSAPP)
        order = {
            "order_id": "ORD-1",
            "item_count": 2,
            "order_title": "Pedido de camisetas",
            "items_identifiable": True,
            "items": [
                {"productId": "PROD-1", "quantity": 1},
                {"productId": "PROD-2", "quantity": 3},
            ],
        }

        process_new_handover(self.db, router, contact=waiting, last_order=order)

        self.assertTrue(router.sent)
        text = router.sent[0]["text"]
        self.assertIn("Camiseta", text)
        # Ordered quantity (3 units of PROD-2) must survive end to end, not
        # just the resolved name/price (critic finding).
        self.assertIn("Boné x3", text)

    def test_partial_catalog_resolution_flags_the_unresolved_items(self):
        """Only PROD-1 is in the local `catalog-product-sync` cache; PROD-2
        is requested but unresolved — the notification must say so instead
        of silently showing a 1-item order (critic finding)."""
        self.db.upsert_catalog_products(
            [{"product_id": "PROD-1", "nome": "Camiseta", "preco": 49.9, "disponivel": True}]
        )
        contact = self.db.create_contact(phone="5511888888888", push_name="Maria")
        self.db.enroll_handover(contact.id, motivo="pedido_catalogo", prioridade=1)
        waiting = self.db.get_contact_waiting("5511888888888")
        router = FakeClient(WHATSAPP)
        order = {
            "order_id": "ORD-3",
            "item_count": 2,
            "order_title": "Pedido misto",
            "items_identifiable": True,
            "items": [
                {"productId": "PROD-1", "quantity": 1},
                {"productId": "PROD-2", "quantity": 1},
            ],
        }

        process_new_handover(self.db, router, contact=waiting, last_order=order)

        self.assertTrue(router.sent)
        text = router.sent[0]["text"]
        self.assertIn("Camiseta", text)
        self.assertIn("não identificado", text)

    def test_unidentifiable_order_warns_the_attendant(self):
        contact = self.db.create_contact(phone="5511888888888", push_name="Maria")
        self.db.enroll_handover(contact.id, motivo="pedido_catalogo", prioridade=1)
        waiting = self.db.get_contact_waiting("5511888888888")
        router = FakeClient(WHATSAPP)
        order = {
            "order_id": "ORD-2",
            "item_count": 3,
            "order_title": "whatbot",
            "items_identifiable": False,
            "items": [{"quantity": 1}, {"quantity": 1}, {"quantity": 1}],
        }

        process_new_handover(self.db, router, contact=waiting, last_order=order)

        self.assertTrue(router.sent)
        text = router.sent[0]["text"]
        self.assertIn("itens não identificados", text)
        self.assertIn("confirmar com o cliente", text)

    def test_no_signal_still_sends_a_well_formed_notification(self):
        contact = self.db.create_contact(phone="5511888888888", push_name="Maria")
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")
        waiting = self.db.get_contact_waiting("5511888888888")
        router = FakeClient(WHATSAPP)

        process_new_handover(self.db, router, contact=waiting)

        self.assertTrue(router.sent)
        text = router.sent[0]["text"]
        self.assertIn("🆕 *Novo na fila*", text)
        # A brand-new lead still gets a real, one-line stage — never a
        # blank/broken trailing section.
        self.assertIn("Estágio: novo lead", text)
        self.assertNotIn("\n\n\n", text)


class TestFormatWaitingListUsesContactSummary(unittest.TestCase):
    """handover-summary-for-agent (Decisão 3, design.md): `format_waiting_list`
    with `include_last_message=True` reuses `build_contact_summary` instead
    of the old raw 120-char message preview (tasks.md 2.2/3.5)."""

    def test_includes_stage_and_interest_instead_of_raw_preview(self):
        db = FakeDatabase()
        contact = db.create_contact(phone="5511888888888", push_name="Maria")
        db.update_contact_session_state(contact.id, {"item_interesse": ["natação"]})
        db.set_contact_status(contact.id, "interessado")
        db.save_message(contact.id, direction="in", text="Quanto custa a natação?")
        db.enroll_handover(contact.id, motivo="pedido_do_cliente")
        waiting = db.get_waiting_contacts()

        text = format_waiting_list(waiting, "Fila", include_last_message=True, db=db)

        self.assertIn("Estágio: interessado", text)
        self.assertIn("Interesse: natação", text)
        # The old raw-preview label is gone — replaced by the summary.
        self.assertNotIn("Última msg:", text)

    def test_no_regression_in_the_overall_list_format(self):
        """List header/footer/contact-line structure is unaffected."""
        db = FakeDatabase()
        contact = db.create_contact(phone="5511888888888", push_name="Maria")
        db.enroll_handover(contact.id, motivo="pedido_do_cliente")
        waiting = db.get_waiting_contacts()

        text = format_waiting_list(waiting, "Fila", include_last_message=True, db=db)

        self.assertIn("Fila", text)
        self.assertIn("Maria", text)
        self.assertIn("Total na fila: 1", text)


class TestStaffOutgoingReactivatesBotImmediately(unittest.TestCase):
    """`admin-attend-keeps-bot-active`: quando a secretaria responde direto
    pelo WhatsApp Business, o contato sai da fila com `ia_ativa=True` e
    `bot_resume_at=None` na hora, sem esperar `AUTO_REACTIVATE_HOURS`."""

    def test_staff_reply_reactivates_bot_immediately(self):
        db = FakeDatabase()
        router = FakeClient(WHATSAPP)
        contact = db.create_contact(phone="5511888888888", push_name="Pedro")
        db.enroll_handover(contact.id, motivo="pedido_do_cliente")

        result = handle_staff_outgoing_message("5511888888888", db, router)

        self.assertTrue(result["ok"])
        self.assertTrue(result.get("auto_attended"))
        updated = db.get_contact_by_phone("5511888888888")
        self.assertTrue(updated.ia_ativa)
        self.assertIsNone(db.contacts[contact.id]["bot_resume_at"])


class TestProcessAutoReactivations(unittest.TestCase):
    """`process_auto_reactivations` with `phone=None` must not break
    (design.md, Importante 6 / tasks.md 6.5) — a real call, not just a name
    referenced from `fakes.py`."""

    def test_reactivates_a_non_whatsapp_contact_without_phone(self):
        db = FakeDatabase()
        contact = db.create_contact(
            canal=INSTAGRAM, external_id="17841400000000000", handle="@maria_ig"
        )
        db.contacts[contact.id]["ia_ativa"] = False
        db.contacts[contact.id]["bot_resume_at"] = datetime.now(timezone.utc) - timedelta(
            hours=1
        )

        reactivated = db.process_auto_reactivations()

        self.assertEqual(reactivated, ["@maria_ig"])
        self.assertTrue(db.contacts[contact.id]["ia_ativa"])
        self.assertIsNone(db.contacts[contact.id]["bot_resume_at"])


if __name__ == "__main__":
    unittest.main()
