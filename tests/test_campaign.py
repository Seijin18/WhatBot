"""campaign-csv-broadcast: importação síncrona de CSV, worker de envio com
fila/limite de taxa e o comando de admin de consulta de status.

`Database`'s campaign methods only have a real implementation against
Postgres (`whatbot/db.py`) — sem rede/Postgres nos testes unitários (ver
`openspec/project.md`), então este arquivo exercita o comportamento via
`FakeDatabase` (`tests/fakes.py`), mesma convenção do resto da suíte
(ver `tests/test_catalog_sync.py`).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from whatbot import main as main_mod
from whatbot.admin import handle_admin_message
from whatbot.admin_nlu import parse_admin_intent
from whatbot.channels import WHATSAPP, ChannelError, ChannelRouter

from fakes import FakeClient, FakeDatabase


def _base_infra_patches(db: FakeDatabase):
    return [
        patch.object(main_mod, "_db", db),
        patch.object(main_mod, "_init_infra", lambda: None),
    ]


class TestImportCampaignCsvParsing(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        patches = _base_infra_patches(self.db)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_all_valid_rows_enqueue_as_pendente(self):
        csv_content = (
            "telefone,mensagem\n"
            "5511999999999,Olá! Confira nossa promoção.\n"
            "5511888888888,Oferta especial para você.\n"
        )

        result = main_mod.import_campaign(csv_content, "lote-1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["enfileiradas"], 2)
        self.assertEqual(result["erros"], [])
        pending = [
            r for r in self.db.campaign_messages.values() if r["status"] == "pendente"
        ]
        self.assertEqual(len(pending), 2)
        self.assertTrue(all(r["lote"] == "lote-1" for r in pending))

    def test_invalid_phone_row_is_reported_without_failing_others(self):
        csv_content = (
            "telefone,mensagem\n"
            "5511999999999,Mensagem válida\n"
            "123,Mensagem com telefone ruim\n"
            "5511888888888,Outra mensagem válida\n"
        )

        result = main_mod.import_campaign(csv_content, "lote-2")

        self.assertTrue(result["ok"])
        self.assertEqual(result["enfileiradas"], 2)
        self.assertEqual(len(result["erros"]), 1)
        self.assertEqual(result["erros"][0]["linha"], 3)
        self.assertIn("telefone", result["erros"][0]["motivo"])
        self.assertEqual(len(self.db.campaign_messages), 2)

    def test_empty_message_row_is_reported_without_failing_others(self):
        csv_content = (
            "telefone,mensagem\n"
            "5511999999999,\n"
            "5511888888888,Mensagem válida\n"
        )

        result = main_mod.import_campaign(csv_content, "lote-3")

        self.assertEqual(result["enfileiradas"], 1)
        self.assertEqual(len(result["erros"]), 1)
        self.assertEqual(result["erros"][0]["linha"], 2)
        self.assertIn("mensagem", result["erros"][0]["motivo"])

    def test_missing_required_columns_returns_error_without_raising(self):
        csv_content = "telefone\n5511999999999\n"

        result = main_mod.import_campaign(csv_content, "lote-4")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_columns")

    def test_tipo_cliente_updates_existing_contact(self):
        contact = self.db.create_contact(
            phone="5511999999999", canal=WHATSAPP, ia_ativa=True
        )
        csv_content = (
            "telefone,mensagem,tipo_cliente\n5511999999999,Oi,b2b\n"
        )

        result = main_mod.import_campaign(csv_content, "lote-5")

        self.assertEqual(result["enfileiradas"], 1)
        self.assertEqual(result["erros"], [])
        self.assertEqual(self.db.contacts[contact.id]["tipo_cliente"], "b2b")

    def test_tipo_cliente_does_not_fail_when_contact_does_not_exist_yet(self):
        csv_content = (
            "telefone,mensagem,tipo_cliente\n5511999999999,Oi,b2b\n"
        )

        result = main_mod.import_campaign(csv_content, "lote-6")

        self.assertEqual(result["enfileiradas"], 1)
        self.assertEqual(result["erros"], [])
        self.assertEqual(len(self.db.contacts), 0)

    def test_invalid_tipo_cliente_value_is_ignored_but_line_still_enqueued(self):
        contact = self.db.create_contact(
            phone="5511999999999", canal=WHATSAPP, ia_ativa=True
        )
        csv_content = (
            "telefone,mensagem,tipo_cliente\n5511999999999,Oi,vip\n"
        )

        result = main_mod.import_campaign(csv_content, "lote-7")

        self.assertEqual(result["enfileiradas"], 1)
        self.assertEqual(result["erros"], [])
        # tipo_cliente inválido: coluna ignorada, valor default preservado.
        self.assertEqual(self.db.contacts[contact.id]["tipo_cliente"], "b2c")


class TestSendCampaignQueueWorker(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        patches = _base_infra_patches(self.db)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _run_with_client(self, client: FakeClient):
        router = ChannelRouter([client])
        with patch.object(main_mod, "_router", router):
            return main_mod.send_campaign_queue()

    def test_respects_campaign_batch_size(self):
        for i in range(5):
            self.db.insert_campaign_message(
                "lote-batch", WHATSAPP, f"551199999000{i}", "Oi"
            )
        client = FakeClient(WHATSAPP)

        with patch.object(main_mod, "CAMPAIGN_BATCH_SIZE", 2):
            result = self._run_with_client(client)

        self.assertEqual(result["processed"], 2)
        self.assertEqual(len(client.sent), 2)
        pending = [
            r for r in self.db.campaign_messages.values() if r["status"] == "pendente"
        ]
        self.assertEqual(len(pending), 3)

    def test_skips_paused_contact_without_calling_send_to_contact(self):
        self.db.create_contact(
            phone="5511999999999", canal=WHATSAPP, ia_ativa=False
        )
        message_id = self.db.insert_campaign_message(
            "lote-pause", WHATSAPP, "5511999999999", "Oi"
        )
        client = FakeClient(WHATSAPP)

        result = self._run_with_client(client)

        self.assertEqual(client.sent, [])
        self.assertEqual(self.db.campaign_messages[message_id]["status"], "pulado")
        self.assertEqual(result["pulado"], 1)
        self.assertEqual(result["enviado"], 0)

    def test_successful_send_marks_enviado_with_timestamp(self):
        message_id = self.db.insert_campaign_message(
            "lote-ok", WHATSAPP, "5511999999999", "Oi"
        )
        client = FakeClient(WHATSAPP)

        result = self._run_with_client(client)

        self.assertEqual(len(client.sent), 1)
        row = self.db.campaign_messages[message_id]
        self.assertEqual(row["status"], "enviado")
        self.assertIsNotNone(row["enviado_em"])
        self.assertEqual(result["enviado"], 1)

    def test_retryable_failure_within_limit_stays_pendente_and_increments_tentativas(
        self,
    ):
        message_id = self.db.insert_campaign_message(
            "lote-retry", WHATSAPP, "5511999999999", "Oi"
        )
        client = FakeClient(WHATSAPP)
        client.raise_error = ChannelError(WHATSAPP, "timeout", retryable=True)

        with patch.object(main_mod, "CAMPAIGN_MAX_RETRIES", 3):
            result = self._run_with_client(client)

        row = self.db.campaign_messages[message_id]
        self.assertEqual(row["status"], "pendente")
        self.assertEqual(row["tentativas"], 1)
        self.assertIsNotNone(row["erro"])
        self.assertEqual(result["pendente"], 1)

    def test_retryable_failure_exhausted_marks_falha(self):
        message_id = self.db.insert_campaign_message(
            "lote-exhausted", WHATSAPP, "5511999999999", "Oi"
        )
        client = FakeClient(WHATSAPP)
        client.raise_error = ChannelError(WHATSAPP, "timeout", retryable=True)

        with patch.object(main_mod, "CAMPAIGN_MAX_RETRIES", 1):
            result = self._run_with_client(client)

        row = self.db.campaign_messages[message_id]
        self.assertEqual(row["status"], "falha")
        self.assertIsNotNone(row["erro"])
        self.assertEqual(result["falha"], 1)

    def test_non_retryable_failure_marks_falha_without_consuming_attempt(self):
        message_id = self.db.insert_campaign_message(
            "lote-fatal", WHATSAPP, "5511999999999", "Oi"
        )
        client = FakeClient(WHATSAPP)
        client.raise_error = ChannelError(WHATSAPP, "número inválido", retryable=False)

        result = self._run_with_client(client)

        row = self.db.campaign_messages[message_id]
        self.assertEqual(row["status"], "falha")
        self.assertEqual(row["tentativas"], 0)
        self.assertEqual(result["falha"], 1)

    def test_contact_lookup_failure_is_fail_closed_and_never_sends(self):
        """Critic feedback: a transient error checking `ia_ativa` (e.g. a
        flaky Postgres connection) must never default to "send anyway" — that
        would defeat design.md's Decisão 4 (never send over an active
        handover/manual pause) exactly when the DB can't confirm either way.
        The row stays `pendente` for the next run, and `tentativas` is left
        untouched — this is an infra failure, not a delivery attempt."""

        def _boom(*args, **kwargs):
            raise RuntimeError("timeout de conexão")

        self.db.get_contact_by_phone = _boom
        message_id = self.db.insert_campaign_message(
            "lote-lookup-fail", WHATSAPP, "5511999999999", "Oi"
        )
        client = FakeClient(WHATSAPP)

        result = self._run_with_client(client)

        self.assertEqual(client.sent, [])
        row = self.db.campaign_messages[message_id]
        self.assertEqual(row["status"], "pendente")
        self.assertEqual(row["tentativas"], 0)
        self.assertEqual(result["pendente"], 1)
        self.assertEqual(result["enviado"], 0)
        self.assertEqual(result["falha"], 0)
        self.assertEqual(result["pulado"], 0)

    def test_sleeps_between_sends_but_not_after_the_last_one(self):
        for i in range(3):
            self.db.insert_campaign_message(
                "lote-sleep", WHATSAPP, f"551199999100{i}", "Oi"
            )
        client = FakeClient(WHATSAPP)

        with patch("whatbot.main.time.sleep") as mocked_sleep:
            self._run_with_client(client)

        self.assertEqual(mocked_sleep.call_count, 2)

    def test_sleeps_between_every_processed_item_in_a_mixed_batch(self):
        """Skipped (`pulado`) rows must pace the batch too, not only real
        sends — the pause applies between every processed row (critic minor
        finding)."""
        self.db.create_contact(phone="5511999999998", canal=WHATSAPP, ia_ativa=False)
        self.db.insert_campaign_message(
            "lote-mixed", WHATSAPP, "5511999999998", "Oi"
        )
        self.db.insert_campaign_message(
            "lote-mixed", WHATSAPP, "5511999999999", "Oi"
        )
        client = FakeClient(WHATSAPP)

        with patch("whatbot.main.time.sleep") as mocked_sleep:
            result = self._run_with_client(client)

        self.assertEqual(result["pulado"], 1)
        self.assertEqual(result["enviado"], 1)
        self.assertEqual(mocked_sleep.call_count, 1)

    def test_does_not_sleep_when_only_one_message_is_processed(self):
        self.db.insert_campaign_message(
            "lote-single", WHATSAPP, "5511999999999", "Oi"
        )
        client = FakeClient(WHATSAPP)

        with patch("whatbot.main.time.sleep") as mocked_sleep:
            self._run_with_client(client)

        mocked_sleep.assert_not_called()

    def test_no_pending_messages_does_not_raise(self):
        client = FakeClient(WHATSAPP)

        result = self._run_with_client(client)

        self.assertTrue(result["ok"])
        self.assertEqual(result["processed"], 0)


class TestCampaignStatusAdminCommand(unittest.TestCase):
    def test_parse_admin_intent_recognizes_como_esta_o_disparo(self):
        intent = parse_admin_intent("como está o disparo lote-agosto")

        self.assertEqual(intent.action, "campaign_status")
        self.assertEqual(intent.query, "lote-agosto")

    def test_parse_admin_intent_recognizes_quantos_faltam_no(self):
        intent = parse_admin_intent("quantos faltam no lote-agosto?")

        self.assertEqual(intent.action, "campaign_status")
        self.assertEqual(intent.query, "lote-agosto")

    def test_get_campaign_status_returns_correct_counts_per_lote(self):
        db = FakeDatabase()
        db.insert_campaign_message("lote-x", WHATSAPP, "5511999999991", "Oi")
        id2 = db.insert_campaign_message("lote-x", WHATSAPP, "5511999999992", "Oi")
        id3 = db.insert_campaign_message("lote-x", WHATSAPP, "5511999999993", "Oi")
        db.insert_campaign_message("lote-y", WHATSAPP, "5511999999994", "Oi")
        db.mark_campaign_message_sent(id2)
        db.mark_campaign_message_failed(id3, "erro qualquer")

        counts = db.get_campaign_status("lote-x")

        self.assertEqual(
            counts, {"pendente": 1, "enviado": 1, "falha": 1, "pulado": 0}
        )

    def test_get_campaign_status_for_unknown_lote_is_zero_filled(self):
        db = FakeDatabase()

        counts = db.get_campaign_status("nunca-importado")

        self.assertEqual(
            counts, {"pendente": 0, "enviado": 0, "falha": 0, "pulado": 0}
        )

    def test_admin_command_replies_with_the_counts(self):
        db = FakeDatabase()
        admin_contact = db.create_contact(phone="5511900000001", canal=WHATSAPP)
        db.insert_campaign_message("lote-z", WHATSAPP, "5511999999991", "Oi")
        id2 = db.insert_campaign_message("lote-z", WHATSAPP, "5511999999992", "Oi")
        db.mark_campaign_message_sent(id2)
        client = FakeClient(WHATSAPP)
        router = ChannelRouter([client])

        result = handle_admin_message(
            phone="5511900000001",
            text="como está o disparo lote-z",
            db=db,
            router=router,
            contact_id=admin_contact.id,
        )

        self.assertTrue(result["ok"])
        reply = result["reply"]
        self.assertIn("lote-z", reply)
        self.assertIn("Pendente: 1", reply)
        self.assertIn("Enviado: 1", reply)
        self.assertIn("Falha: 0", reply)
        self.assertIn("Pulado: 0", reply)


if __name__ == "__main__":
    unittest.main()
