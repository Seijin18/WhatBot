"""End-to-end tests at the `main()` seam.

`windmill/f/whatbot/handler.py` calls `whatbot.main.main(payload)` with the raw
Evolution API body, so entering through the same door covers the real path:
payload parsing, admin routing, the domain modules and the outbound router.

These are the only tests that exercise the `whatsapp` -> `router` rename across
`main`, `domain`, `queue` and `admin` — every one of those modules is otherwise
reachable only with a live Postgres.
"""

import itertools
import os
import unittest
from unittest.mock import patch

from whatbot import main as main_mod
from whatbot.channels import INSTAGRAM, WHATSAPP, ChannelError, ChannelRouter
from whatbot.channels.instagram import CAUSE_WINDOW_EXPIRED

from fakes import FakeClient, FakeDatabase, FakeLlm

ADMIN_PHONE = "5511900000001"
CUSTOMER_PHONE = "5511999999999"
IGSID = "17841400000000000"

BASE_ENV = {
    "ADMIN_NOTIFY_PHONES": ADMIN_PHONE,
    "TEST_MODE": "false",
    "GEMINI_API_KEY": "test-key",
}

# Unique-by-default message id per `evolution_payload()` call, so unrelated
# tests never collide on the webhook-idempotency check (instagram-ingestion-
# service) just because they share the fixture's old hardcoded "MSG1". Tests
# that specifically exercise the duplicate path pass `msg_id=` explicitly.
_msg_id_counter = itertools.count(1)


def evolution_payload(
    phone: str, text: str, push_name: str = "Maria", msg_id: str | None = None
) -> dict:
    """A customer message exactly as the Evolution API webhook delivers it."""
    if msg_id is None:
        msg_id = f"MSG{next(_msg_id_counter)}"
    return {
        "event": "messages.upsert",
        "instance": "whatbot",
        "data": {
            "key": {
                "remoteJid": f"{phone}@s.whatsapp.net",
                "fromMe": False,
                "id": msg_id,
            },
            "pushName": push_name,
            "message": {"conversation": text},
        },
    }


def staff_reply_payload(phone: str, text: str = "Oi, já te respondo") -> dict:
    """A `fromMe` message: the secretariat answering from WhatsApp Business."""
    return {
        "event": "messages.upsert",
        "instance": "whatbot",
        "data": {
            "key": {
                "remoteJid": f"{phone}@s.whatsapp.net",
                "fromMe": True,
                "id": "MSG2",
            },
            "message": {"conversation": text},
        },
    }


class MainE2ETestCase(unittest.TestCase):
    """Wires the module globals to fakes and neutralizes infra bootstrap."""

    llm_reply = "Temos judô, natação e ginástica. Passe na secretaria para detalhes."
    llm_unavailable = False

    def setUp(self):
        self.db = FakeDatabase()
        self.wa = FakeClient(WHATSAPP)
        self.ig = FakeClient(INSTAGRAM)
        self.router = ChannelRouter([self.wa, self.ig])
        self.llm = FakeLlm(reply=self.llm_reply, unavailable=self.llm_unavailable)

        patches = [
            patch.object(main_mod, "_db", self.db),
            patch.object(main_mod, "_router", self.router),
            patch.object(main_mod, "_llm", self.llm),
            patch.object(main_mod, "_init_infra", lambda: None),
            patch.dict(os.environ, BASE_ENV, clear=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    # -- helpers ---------------------------------------------------------

    def customer_sends(self, text: str, phone: str = CUSTOMER_PHONE) -> dict:
        return main_mod.main(evolution_payload(phone, text))

    def texts_sent_on(self, client: FakeClient) -> list[str]:
        return [m["text"] for m in client.sent]

    def assert_nothing_sent_on(self, client: FakeClient) -> None:
        self.assertEqual(client.sent, [], f"nada deveria sair por {client.canal}")


class TestCustomerReply(MainE2ETestCase):
    def test_evolution_payload_reaches_the_whatsapp_client(self):
        result = self.customer_sends("Quais modalidades vocês têm?")

        self.assertTrue(result["ok"])
        self.assertTrue(result["sent"])
        self.assertEqual(len(self.wa.sent), 1)
        self.assertEqual(self.wa.sent[0]["to"], CUSTOMER_PHONE)
        self.assertEqual(self.wa.sent[0]["source"], "bot")
        self.assertTrue(self.wa.sent[0]["text"])
        self.assert_nothing_sent_on(self.ig)

    def test_contact_and_messages_are_persisted(self):
        self.customer_sends("Quais modalidades vocês têm?")

        contact = self.db.get_contact_by_phone(CUSTOMER_PHONE)
        self.assertIsNotNone(contact)
        self.assertEqual(contact.push_name, "Maria")
        directions = [m["direction"] for m in self.db.messages]
        self.assertEqual(directions, ["in", "out"])

    def test_inactive_bot_short_circuits_without_sending(self):
        contact = self.db.create_contact(phone=CUSTOMER_PHONE, ia_ativa=False)
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")

        result = self.customer_sends("ainda estou esperando")

        self.assertTrue(result["handed_to_human"])
        self.assert_nothing_sent_on(self.wa)


class TestChannelRouting(MainE2ETestCase):
    """The invariant from the plan: customer on their channel, admin on WhatsApp."""

    def test_customer_on_another_channel_is_answered_there(self):
        result = main_mod.process_customer_message(
            IGSID, "Quais modalidades vocês têm?", canal=INSTAGRAM
        )

        self.assertTrue(result["ok"])
        self.assertEqual(len(self.ig.sent), 1)
        self.assertEqual(self.ig.sent[0]["to"], IGSID)
        self.assert_nothing_sent_on(self.wa)

    def test_handover_answers_customer_on_channel_and_admin_on_whatsapp(self):
        result = main_mod.process_customer_message(
            IGSID, "quero falar com a secretaria", canal=INSTAGRAM
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["handed_to_human"])

        # Customer got the handover confirmation on Instagram.
        self.assertEqual(len(self.ig.sent), 1)
        self.assertEqual(self.ig.sent[0]["source"], "handover")
        self.assertTrue(self.ig.sent[0]["human_agent"])

        # Secretariat was notified on WhatsApp, never on Instagram.
        self.assertTrue(self.wa.sent)
        admin_sends = [m for m in self.wa.sent if m["to"] == ADMIN_PHONE]
        self.assertTrue(admin_sends)
        self.assertIn("Novo na fila", admin_sends[0]["text"])
        # Secretariat must know which channel to answer on, not just the
        # customer's readable label (channel-queue-visibility).
        self.assertIn("Instagram", admin_sends[0]["text"])

    def test_handover_on_whatsapp_notifies_admin_and_customer(self):
        result = self.customer_sends("quero falar com a secretaria")

        self.assertTrue(result["handed_to_human"])
        recipients = {m["to"] for m in self.wa.sent}
        self.assertEqual(recipients, {CUSTOMER_PHONE, ADMIN_PHONE})
        self.assert_nothing_sent_on(self.ig)

    def test_handover_puts_contact_in_queue(self):
        self.customer_sends("quero falar com a secretaria")

        waiting = self.db.get_waiting_contacts()
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0].phone, CUSTOMER_PHONE)


class TestAdminCommands(MainE2ETestCase):
    def test_admin_assume_replies_on_admin_channel(self):
        contact = self.db.create_contact(phone=CUSTOMER_PHONE, push_name="Maria")
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")

        result = main_mod.main(
            evolution_payload(ADMIN_PHONE, "assumir Maria", push_name="Secretaria")
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["admin_command"])
        self.assertIn("assumiu", result["reply"])

        waiting = self.db.get_contact_waiting(CUSTOMER_PHONE)
        self.assertEqual(waiting.assumido_por, ADMIN_PHONE)

        confirmations = [m for m in self.wa.sent if m["to"] == ADMIN_PHONE]
        self.assertTrue(confirmations)
        self.assert_nothing_sent_on(self.ig)

    def test_admin_queue_listing_reaches_the_admin(self):
        contact = self.db.create_contact(phone=CUSTOMER_PHONE, push_name="Maria")
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")

        result = main_mod.main(evolution_payload(ADMIN_PHONE, "fila"))

        self.assertTrue(result["admin_command"])
        self.assertEqual(self.wa.sent[-1]["to"], ADMIN_PHONE)
        self.assertEqual(self.wa.sent[-1]["source"], "admin")

    def test_admin_assumes_and_completes_a_non_whatsapp_contact(self):
        """`admin.py` must resolve `(canal, external_id)`, not just `phone`
        (design.md, Decisão 4) — the secretariat still has commands for a
        contact that never has a `phone`."""
        contact = self.db.create_contact(
            canal=INSTAGRAM, external_id=IGSID, push_name="Joana IG"
        )
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")

        assume_result = main_mod.main(
            evolution_payload(ADMIN_PHONE, "assumo a Joana", push_name="Secretaria")
        )
        self.assertTrue(assume_result["admin_command"])
        self.assertIn("assumiu", assume_result["reply"])

        waiting = self.db.get_contact_waiting(IGSID, canal=INSTAGRAM)
        self.assertIsNotNone(waiting)
        self.assertEqual(waiting.assumido_por, ADMIN_PHONE)

        complete_result = main_mod.main(
            evolution_payload(ADMIN_PHONE, "finalizei com a Joana")
        )
        self.assertTrue(complete_result["admin_command"])
        self.assertIn("atendido", complete_result["reply"])
        self.assertIsNone(self.db.get_contact_waiting(IGSID, canal=INSTAGRAM))
        self.assert_nothing_sent_on(self.ig)

    def test_admin_assumes_and_completes_a_contact_with_only_a_handle(self):
        """The realistic shape of a fresh Instagram contact: no `push_name`
        at all, only `handle` — the secretariat must still be able to find
        and act on it by handle (design.md, Bloqueador 2)."""
        contact = self.db.create_contact(
            canal=INSTAGRAM, external_id=IGSID, handle="@joana_ig"
        )
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")

        assume_result = main_mod.main(
            evolution_payload(ADMIN_PHONE, "assumo a joana_ig", push_name="Secretaria")
        )
        self.assertTrue(assume_result["admin_command"])
        self.assertIn("assumiu", assume_result["reply"])

        waiting = self.db.get_contact_waiting(IGSID, canal=INSTAGRAM)
        self.assertIsNotNone(waiting)
        self.assertEqual(waiting.assumido_por, ADMIN_PHONE)

        complete_result = main_mod.main(
            evolution_payload(ADMIN_PHONE, "finalizei com a joana_ig")
        )
        self.assertTrue(complete_result["admin_command"])
        self.assertIn("atendido", complete_result["reply"])
        self.assertIsNone(self.db.get_contact_waiting(IGSID, canal=INSTAGRAM))
        self.assert_nothing_sent_on(self.ig)


class TestCrossChannelIdentity(MainE2ETestCase):
    """Requirement 'Identidade do contato por canal', cenário 'Mesma
    identidade externa em canais diferentes'."""

    def test_same_external_id_in_different_channels_does_not_collide(self):
        same_id = "5511999999999"
        wa_contact = self.db.create_contact(canal=WHATSAPP, external_id=same_id)
        ig_contact = self.db.create_contact(canal=INSTAGRAM, external_id=same_id)

        self.assertNotEqual(wa_contact.id, ig_contact.id)
        self.assertEqual(wa_contact.phone, same_id)
        self.assertIsNone(ig_contact.phone)

        found_wa = self.db.get_contact_by_phone(same_id, canal=WHATSAPP)
        found_ig = self.db.get_contact_by_phone(same_id, canal=INSTAGRAM)
        self.assertEqual(found_wa.id, wa_contact.id)
        self.assertEqual(found_ig.id, ig_contact.id)


class TestStaffOutgoing(MainE2ETestCase):
    def test_staff_reply_auto_completes_the_queue_entry(self):
        contact = self.db.create_contact(phone=CUSTOMER_PHONE, push_name="Maria")
        self.db.enroll_handover(contact.id, motivo="pedido_do_cliente")

        result = main_mod.main(staff_reply_payload(CUSTOMER_PHONE))

        self.assertTrue(result["ok"])
        self.assertTrue(result["auto_attended"])
        self.assertIsNone(self.db.get_contact_waiting(CUSTOMER_PHONE))

        admin_sends = [m for m in self.wa.sent if m["to"] == ADMIN_PHONE]
        self.assertTrue(admin_sends)
        self.assertIn("atendido via WhatsApp Business", admin_sends[0]["text"])

    def test_staff_reply_to_unknown_contact_is_ignored(self):
        result = main_mod.main(staff_reply_payload("5511888888888"))

        self.assertTrue(result["ignored"])
        self.assert_nothing_sent_on(self.wa)


class TestUnsupportedChannel(MainE2ETestCase):
    """D2 — a channel the app cannot handle stops at the edge."""

    def test_payload_with_unknown_channel_is_refused(self):
        result = main_mod.main(
            {"canal": "telegram", "from_number": CUSTOMER_PHONE, "text": "oi"}
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unsupported_channel")
        self.assertIn("telegram", result["detail"])

    def test_nothing_is_touched_when_the_channel_is_refused(self):
        main_mod.main(
            {"canal": "telegram", "from_number": CUSTOMER_PHONE, "text": "oi"}
        )

        self.assertEqual(self.db.contacts, {})
        self.assertEqual(self.llm.calls, [])
        self.assert_nothing_sent_on(self.wa)
        self.assert_nothing_sent_on(self.ig)


class TestAdminSimulation(MainE2ETestCase):
    """D1 — a simulation must carry the simulated contact's channel.

    A simulation never actually messages the customer, so the defect has no
    visible effect today; it is plumbing that only bites once a non-WhatsApp
    contact can be simulated. These tests pin the contract at the seam where
    the channel is handed over.
    """

    def test_simulation_forwards_the_channel(self):
        with patch.object(main_mod, "process_customer_message") as process:
            process.return_value = {"ok": True, "model_reply": "resposta"}
            main_mod.run_admin_simulation(
                ADMIN_PHONE, IGSID, "Quais modalidades?", canal=INSTAGRAM
            )

        self.assertEqual(process.call_args.kwargs["canal"], INSTAGRAM)

    def test_simulation_without_a_channel_defaults_to_whatsapp(self):
        with patch.object(main_mod, "process_customer_message") as process:
            process.return_value = {"ok": True, "model_reply": "resposta"}
            main_mod.run_admin_simulation(ADMIN_PHONE, CUSTOMER_PHONE, "oi")

        self.assertEqual(process.call_args.kwargs["canal"], WHATSAPP)

    def test_simulation_reports_back_on_the_admin_channel(self):
        result = main_mod.run_admin_simulation(
            ADMIN_PHONE, IGSID, "Quais modalidades?", canal=INSTAGRAM
        )

        self.assertEqual(result["simulated_as"], IGSID)
        # The simulated customer is never really messaged...
        self.assert_nothing_sent_on(self.ig)
        # ...but the admin gets the transcript back on the admin channel.
        self.assertEqual(len(self.wa.sent), 1)
        self.assertEqual(self.wa.sent[0]["to"], ADMIN_PHONE)
        self.assertEqual(self.wa.sent[0]["source"], "simulation")


class TestQueueMaintenance(MainE2ETestCase):
    def test_check_queue_runs_without_arguments(self):
        """Production calls `check_queue()` bare from a scheduled Windmill job."""
        result = main_mod.check_queue()

        self.assertTrue(result["ok"])
        self.assertIn("long_wait", result)


class TestModelUnavailable(MainE2ETestCase):
    llm_unavailable = True

    def test_unavailable_model_still_answers_on_the_right_channel(self):
        result = main_mod.process_customer_message(
            IGSID, "Vocês têm natação infantil?", canal=INSTAGRAM
        )

        # Either the knowledge fallback answers or the system notice goes out,
        # but whichever it is must reach the customer on their own channel.
        if result.get("ok"):
            self.assertEqual(len(self.ig.sent), 1)
        else:
            self.assertEqual(self.ig.sent[0]["source"], "system")
            self.assertIn(main_mod.MODEL_UNAVAILABLE_MSG, self.texts_sent_on(self.ig))
        self.assert_nothing_sent_on(self.wa)


class TestSendFailureHealthAlertFiresFromTheRealSendPath(MainE2ETestCase):
    """Critic BLOQUEADOR 1: `SendFailureMonitor`/`alert_fail_streak` had an
    isolated test in `tests/test_instagram_health.py`, but nothing in the
    real send path ever called them — the alert never fired in production.
    This drives failures through `process_customer_message()` (the actual
    Instagram send point in `whatbot/main.py`), not through
    `instagram_health` directly, so it breaks if the wiring is removed."""

    def test_reaching_the_threshold_alerts_the_admin_exactly_once(self):
        self.ig.raise_error = ChannelError(
            INSTAGRAM, "instabilidade simulada", retryable=True
        )
        with patch.dict(os.environ, {"IG_ALERT_FAIL_STREAK": "3"}):
            for i in range(3):
                result = main_mod.process_customer_message(
                    IGSID, f"Mensagem {i}", canal=INSTAGRAM
                )
                self.assertFalse(result["ok"])

        # Only on the third (threshold-crossing) failure does the admin get
        # alerted — via WhatsApp, the admin channel, regardless of which
        # channel is failing.
        self.assertEqual(len(self.wa.sent), 1)
        self.assertIn("3", self.wa.sent[0]["text"])
        self.assertEqual(self.wa.sent[0]["to"], ADMIN_PHONE)

    def test_a_success_in_between_resets_the_streak(self):
        with patch.dict(os.environ, {"IG_ALERT_FAIL_STREAK": "2"}):
            self.ig.raise_error = ChannelError(INSTAGRAM, "falha", retryable=True)
            main_mod.process_customer_message(IGSID, "Oi", canal=INSTAGRAM)

            self.ig.raise_error = None
            main_mod.process_customer_message(IGSID, "Oi de novo", canal=INSTAGRAM)

            self.ig.raise_error = ChannelError(INSTAGRAM, "falha", retryable=True)
            main_mod.process_customer_message(IGSID, "Mais uma", canal=INSTAGRAM)

        # Only one failure since the reset — never reached the threshold of 2.
        self.assertEqual(self.wa.sent, [])


class TestMessagingWindowBlocksAutomaticSend(MainE2ETestCase):
    """`instagram-messaging-window`: a send refused for being outside the
    messaging window must never surface as an error to the customer — the
    channel failure is absorbed the same way any other `ChannelError` is
    (see `whatbot/main.py::process_customer_message`)."""

    def test_automatic_reply_blocked_outside_the_window_reaches_no_one(self):
        self.ig.raise_error = ChannelError(
            INSTAGRAM, "janela expirada", cause=CAUSE_WINDOW_EXPIRED
        )

        result = main_mod.process_customer_message(
            IGSID, "Vocês têm natação infantil?", canal=INSTAGRAM
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "send_failed")
        self.assertEqual(result["canal"], INSTAGRAM)
        # Nothing was delivered — not the reply, not an error message either.
        self.assert_nothing_sent_on(self.ig)
        self.assert_nothing_sent_on(self.wa)


class TestLastInboundAtIsPersisted(MainE2ETestCase):
    """`instagram-messaging-window` task 1.1: a real inbound customer message
    must feed the Instagram messaging-window check by recording
    `last_inbound_at`. Without this, `InstagramClient._check_messaging_window`
    (fed via `whatbot/db.py::get_last_inbound_at`) always sees `None` and
    fail-closed blocks every send, window or no window."""

    def test_real_customer_message_records_last_inbound_at(self):
        self.customer_sends("Quais modalidades vocês têm?")

        self.assertIsNotNone(self.db.get_last_inbound_at(CUSTOMER_PHONE, canal=WHATSAPP))


class TestAdminSimulationDoesNotTouchLastInboundAt(MainE2ETestCase):
    """Bloqueador 3: `run_admin_simulation` must never make the system
    believe the real customer just wrote in — that would reopen a messaging
    window that is actually closed and let real sends through Meta would
    refuse/penalize."""

    def test_simulation_does_not_update_last_inbound_at(self):
        self.db.create_contact(canal=INSTAGRAM, external_id=IGSID, handle="@maria_ig")
        self.assertIsNone(self.db.get_last_inbound_at(IGSID, canal=INSTAGRAM))

        main_mod.run_admin_simulation(
            ADMIN_PHONE, IGSID, "Quais modalidades?", canal=INSTAGRAM
        )

        self.assertIsNone(self.db.get_last_inbound_at(IGSID, canal=INSTAGRAM))


class TestAdminSimulationDoesNotCorruptTheRealContact(MainE2ETestCase):
    """A critic reviewing `instagram-messaging-window` found that
    `run_admin_simulation` corrupted the real contact whenever `sim_phone`
    collided with an existing customer: `push_name` was overwritten with
    "Simulado por ...", and the simulated exchange was written into that
    contact's real message history / session state. `enroll_handover` even
    deactivated the bot and enrolled the real contact in the secretariat
    queue when the simulated text triggered a handover. None of that may
    leave a trace on the real contact, mirroring the `last_inbound_at` fix
    above."""

    def test_push_name_of_existing_contact_is_not_overwritten(self):
        self.db.create_contact(
            canal=INSTAGRAM, external_id=IGSID, handle="@maria_ig", push_name="Maria Real"
        )

        main_mod.run_admin_simulation(
            ADMIN_PHONE, IGSID, "Quais modalidades?", canal=INSTAGRAM
        )

        contact = self.db.get_contact_by_phone(IGSID, canal=INSTAGRAM)
        self.assertEqual(contact.push_name, "Maria Real")

    def test_simulation_does_not_write_to_the_real_message_history(self):
        self.db.create_contact(
            canal=INSTAGRAM, external_id=IGSID, handle="@maria_ig", push_name="Maria Real"
        )

        main_mod.run_admin_simulation(
            ADMIN_PHONE, IGSID, "Quais modalidades?", canal=INSTAGRAM
        )

        contact = self.db.get_contact_by_phone(IGSID, canal=INSTAGRAM)
        self.assertEqual(self.db.get_recent_messages(contact.id), [])

    def test_simulation_does_not_persist_session_state(self):
        self.db.create_contact(
            canal=INSTAGRAM, external_id=IGSID, handle="@maria_ig", push_name="Maria Real"
        )

        main_mod.run_admin_simulation(
            ADMIN_PHONE, IGSID, "Quais modalidades?", canal=INSTAGRAM
        )

        contact = self.db.get_contact_by_phone(IGSID, canal=INSTAGRAM)
        self.assertEqual(contact.session_state, {})

    def test_simulated_handover_does_not_enroll_the_real_contact(self):
        self.db.create_contact(
            canal=INSTAGRAM, external_id=IGSID, handle="@maria_ig", push_name="Maria Real"
        )

        main_mod.run_admin_simulation(
            ADMIN_PHONE, IGSID, "quero falar com a secretaria", canal=INSTAGRAM
        )

        contact = self.db.get_contact_by_phone(IGSID, canal=INSTAGRAM)
        self.assertTrue(contact.ia_ativa)
        self.assertIsNone(contact.handover_at)
        self.assertEqual(self.db.get_recent_messages(contact.id), [])


class TestWebhookIdempotency(MainE2ETestCase):
    """`instagram-ingestion-service`, Requirement "Idempotência de entrega de
    webhook": a reentrega do mesmo `message_id` não pode gerar segunda
    resposta. Verificado aqui na porta `main()`, sem precisar do serviço
    FastAPI de pé — fecha o bloqueio de raiz de forma independente do
    transporte HTTP (WhatsApp síncrono ou `whatbot/ingress.py` para o
    Instagram usam a mesma checagem)."""

    def test_second_delivery_of_the_same_message_id_is_discarded(self):
        payload = evolution_payload(
            CUSTOMER_PHONE, "Quais modalidades vocês têm?", msg_id="dup-1"
        )

        first = main_mod.main(payload)
        second = main_mod.main(payload)

        self.assertTrue(first["ok"])
        self.assertTrue(first.get("sent"))
        self.assertEqual(len(self.wa.sent), 1)

        self.assertTrue(second["ok"])
        self.assertTrue(second.get("ignored"))
        self.assertEqual(second.get("reason"), "duplicate_message_id")
        # Nothing new went out on the second delivery.
        self.assertEqual(len(self.wa.sent), 1)

    def test_different_message_ids_are_both_processed(self):
        main_mod.main(
            evolution_payload(CUSTOMER_PHONE, "Oi", msg_id="a-1")
        )
        main_mod.main(
            evolution_payload(CUSTOMER_PHONE, "Quais modalidades?", msg_id="a-2")
        )

        self.assertEqual(len(self.wa.sent), 2)


class TestIdempotencyRollbackOnFailure(MainE2ETestCase):
    """Critic BLOQUEADOR 2: idempotência gravada antes de processar, sem
    reverter em caso de falha, perdia a mensagem para sempre — a reentrega da
    Meta era descartada como duplicata mesmo sem o cliente ter recebido
    resposta. A primeira entrega falha *depois* que o evento já foi
    registrado (aqui, no envio real ao canal); a segunda entrega do mesmo
    `message_id` deve ser reprocessada, não descartada."""

    def test_second_delivery_is_reprocessed_after_the_first_fails_mid_flow(self):
        payload = evolution_payload(
            CUSTOMER_PHONE, "Quais modalidades vocês têm?", msg_id="fail-then-retry"
        )
        self.wa.raise_error = ChannelError(
            WHATSAPP, "instabilidade simulada", cause="simulated", retryable=True
        )

        first = main_mod.main(payload)

        self.assertFalse(first["ok"])
        self.assertEqual(first.get("error"), "send_failed")
        self.assertEqual(self.wa.sent, [])

        # The customer never actually got a response — the retry must be
        # processed again, not silently discarded.
        self.wa.raise_error = None
        second = main_mod.main(payload)

        self.assertTrue(second["ok"])
        self.assertTrue(second.get("sent"))
        self.assertNotEqual(second.get("reason"), "duplicate_message_id")
        self.assertEqual(len(self.wa.sent), 1)


class TestNoDuplicateSendWhenPostSendBookkeepingFails(MainE2ETestCase):
    """Critic (novo bloqueador, pós-correção do BLOQUEADOR 2): o rollback de
    idempotência em `main()` reage a QUALQUER `ok: False` de
    `process_customer_message`, inclusive quando a mensagem já foi entregue
    de verdade ao cliente e só o bookkeeping pós-envio (`_db.save_message`)
    falhou. Sem proteção, isso derruba o retorno para `ok: False`, `main()`
    desfaz o registro de idempotência, e a reentrega do mesmo `message_id`
    reprocessa do zero — reenviando a resposta ao cliente real pela segunda
    vez. A primeira entrega deve retornar `ok: True` apesar da falha de
    bookkeeping, então a segunda entrega do mesmo `message_id` deve ser
    descartada como duplicata (nenhum envio adicional ao canal)."""

    def test_second_delivery_does_not_resend_after_post_send_save_message_fails(self):
        payload = evolution_payload(
            CUSTOMER_PHONE,
            "Quais modalidades vocês têm?",
            msg_id="send-ok-bookkeeping-fails",
        )

        original_save_message = self.db.save_message
        calls = {"n": 0}

        def flaky_save_message(contact_id, direction, text):
            calls["n"] += 1
            # Let the inbound save (direction="in") succeed so the flow
            # reaches the real send; blow up only on the post-send bookkeeping
            # write (direction="out") of this first delivery.
            if direction == "out" and calls["n"] == 2:
                raise RuntimeError("soneca de conexão do Postgres simulada")
            return original_save_message(contact_id, direction, text)

        self.db.save_message = flaky_save_message

        first = main_mod.main(payload)

        # The reply already reached the real customer — a bookkeeping hiccup
        # must not be reported as a delivery failure.
        self.assertTrue(first["ok"])
        self.assertTrue(first.get("sent"))
        self.assertEqual(len(self.wa.sent), 1)

        second = main_mod.main(payload)

        # Same `message_id` redelivered: must be discarded as a duplicate,
        # never reprocessed/resent, since the first delivery already
        # succeeded from the customer's point of view.
        self.assertTrue(second["ok"])
        self.assertEqual(second.get("reason"), "duplicate_message_id")
        self.assertEqual(len(self.wa.sent), 1)


class TestNoDuplicateHandoverSendWhenPostSendBookkeepingFails(MainE2ETestCase):
    """Mesma classe de bug do teste acima, no caminho de handover
    (`whatbot/domain.py::executar_handover_para_secretaria`): a confirmação de
    handover já foi entregue ao cliente real quando o bookkeeping pós-envio
    (`db.save_message`/`db.enroll_handover`) falha. Sem proteção, isso
    derrubava o retorno para `ok: False`, `main()` desfazia o registro de
    idempotência, e a reentrega do mesmo `message_id` reprocessava do zero —
    reenviando a confirmação de handover ao cliente real pela segunda vez."""

    def test_second_delivery_does_not_resend_handover_after_post_send_save_message_fails(
        self,
    ):
        payload = evolution_payload(
            CUSTOMER_PHONE,
            "quero falar com a secretaria",
            msg_id="handover-ok-bookkeeping-fails",
        )

        original_save_message = self.db.save_message
        calls = {"n": 0}

        def flaky_save_message(contact_id, direction, text):
            calls["n"] += 1
            # Let the inbound save (direction="in") succeed so the flow
            # reaches the real send; blow up only on the post-send bookkeeping
            # write (direction="out", inside executar_handover_para_secretaria)
            # of this first delivery.
            if direction == "out" and calls["n"] == 2:
                raise RuntimeError("soneca de conexão do Postgres simulada")
            return original_save_message(contact_id, direction, text)

        self.db.save_message = flaky_save_message

        first = main_mod.main(payload)

        # The handover confirmation already reached the real customer — a
        # bookkeeping hiccup must not be reported as a delivery failure.
        self.assertTrue(first["ok"])
        self.assertTrue(first.get("handed_to_human"))
        self.assertEqual(len(self.wa.sent), 1)

        second = main_mod.main(payload)

        # Same `message_id` redelivered: must be discarded as a duplicate,
        # never reprocessed/resent, since the first delivery already
        # succeeded from the customer's point of view.
        self.assertTrue(second["ok"])
        self.assertEqual(second.get("reason"), "duplicate_message_id")
        self.assertEqual(len(self.wa.sent), 1)


class TestInstagramClientRegistration(unittest.TestCase):
    """`_register_instagram_client_if_configured` (instagram-live-smoke-test,
    tarefa 3.1): o cliente só é registrado depois que uma credencial real
    existe em `canal_credenciais` (via `scripts/ig_oauth.py`), para o
    WhatsApp continuar funcionando sem exigir OAuth do Instagram já feito."""

    def test_no_credential_leaves_instagram_unregistered(self):
        db = FakeDatabase()
        router = ChannelRouter()

        main_mod._register_instagram_client_if_configured(router, db)

        self.assertNotIn(INSTAGRAM, router.channels)
        with self.assertRaises(main_mod.UnknownChannelError):
            router.send_text(IGSID, "oi", canal=INSTAGRAM)

    def test_credential_present_registers_a_working_client(self):
        db = FakeDatabase()
        db.upsert_channel_credential(
            INSTAGRAM, access_token="tok-123", account_id="acc-456"
        )
        router = ChannelRouter()

        main_mod._register_instagram_client_if_configured(router, db)

        self.assertIn(INSTAGRAM, router.channels)
        client = router.client_for(INSTAGRAM)
        self.assertEqual(client.access_token, "tok-123")
        self.assertEqual(client.account_id, "acc-456")
        # `last_inbound_lookup` must be wired to `instagram_last_inbound_lookup`,
        # not left `None` (fail-closed) or bound to the wrong channel.
        contact = db.create_contact(canal=INSTAGRAM, external_id=IGSID)
        db.update_contact_last_inbound(contact.id)
        with patch("whatbot.channels.instagram.requests.post") as post:
            post.return_value.ok = True
            post.return_value.json.return_value = {"message_id": "MSG1"}
            client.send_text(IGSID, "oi")
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
