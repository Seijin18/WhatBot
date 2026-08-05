"""Tests for the FastAPI Instagram ingestion endpoint (`whatbot/ingress.py`).

No real network, no live Postgres, no live LLM: the FastAPI app is exercised
via `TestClient` (in-process ASGI), and `whatbot.main`'s module globals are
patched the same way `tests/test_main_e2e.py` patches them.
"""

import asyncio
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from starlette.requests import Request

from whatbot import ingress
from whatbot import main as main_mod
from whatbot.channels import INSTAGRAM, WHATSAPP, ChannelRouter

from fakes import FakeClient, FakeDatabase, FakeLlm

SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"
IGSID = "17841400000000000"
PAGE_ID = "17841400000000009"

WA_SECRET = "test-wa-app-secret"
WA_VERIFY_TOKEN = "test-wa-verify-token"
WA_PHONE = "16315551234"
WA_PHONE_NUMBER_ID = "1234567890"
WA_WABA_ID = "9876543210"

ENV = {
    "IG_APP_SECRET": SECRET,
    "IG_WEBHOOK_VERIFY_TOKEN": VERIFY_TOKEN,
    "WA_CLOUD_APP_SECRET": WA_SECRET,
    "WA_CLOUD_WEBHOOK_VERIFY_TOKEN": WA_VERIFY_TOKEN,
    "ADMIN_NOTIFY_PHONES": "5511900000001",
    "TEST_MODE": "false",
    "GEMINI_API_KEY": "test-key",
}


def _sign(body: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _message_body(message_id: str = "mid-1", text: str = "oi, tem yoga?") -> bytes:
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": PAGE_ID,
                "time": 1753700000,
                "messaging": [
                    {
                        "sender": {"id": IGSID},
                        "recipient": {"id": PAGE_ID},
                        "timestamp": 1753700000,
                        "message": {"mid": message_id, "text": text},
                    }
                ],
            }
        ],
    }
    return json.dumps(payload).encode("utf-8")


def _wa_message_body(message_id: str = "wamid.1", text: str = "oi, tem yoga?") -> bytes:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WA_WABA_ID,
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550001111",
                                "phone_number_id": WA_PHONE_NUMBER_ID,
                            },
                            "contacts": [
                                {"profile": {"name": "Kerry"}, "wa_id": WA_PHONE}
                            ],
                            "messages": [
                                {
                                    "from": WA_PHONE,
                                    "id": message_id,
                                    "timestamp": "1753700000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    return json.dumps(payload).encode("utf-8")


def _wa_status_body(status_id: str = "wamid.status-1") -> bytes:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WA_WABA_ID,
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550001111",
                                "phone_number_id": WA_PHONE_NUMBER_ID,
                            },
                            "statuses": [
                                {
                                    "id": status_id,
                                    "status": "delivered",
                                    "timestamp": "1753700001",
                                    "recipient_id": WA_PHONE,
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    return json.dumps(payload).encode("utf-8")


class IngressTestCase(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.wa = FakeClient(WHATSAPP)
        self.ig = FakeClient(INSTAGRAM)
        self.router = ChannelRouter([self.wa, self.ig])
        self.llm = FakeLlm(reply="Sim, temos yoga!")

        patches = [
            patch.object(main_mod, "_db", self.db),
            patch.object(main_mod, "_router", self.router),
            patch.object(main_mod, "_llm", self.llm),
            patch.object(main_mod, "_init_infra", lambda: None),
            patch.dict(os.environ, ENV, clear=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        self.client = TestClient(ingress.app)


class TestHandshake(IngressTestCase):
    """Requirement "Autenticidade e velocidade da ingestão": handshake `GET`."""

    def test_valid_token_echoes_the_challenge(self):
        response = self.client.get(
            "/webhook/instagram",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "123456",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "123456")

    def test_invalid_token_is_rejected(self):
        response = self.client.get(
            "/webhook/instagram",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "123456",
            },
        )
        self.assertEqual(response.status_code, 403)


class TestSignatureAtTheEndpoint(IngressTestCase):
    """Cenário "Assinatura inválida": nada é processado quando a assinatura
    não confere."""

    def test_missing_signature_is_rejected_and_nothing_is_processed(self):
        body = _message_body()

        response = self.client.post(
            "/webhook/instagram", content=body, headers={"Content-Type": "application/json"}
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.ig.sent, [])
        self.assertEqual(self.db.contacts, {})

    def test_invalid_signature_is_rejected_and_nothing_is_processed(self):
        body = _message_body()

        response = self.client.post(
            "/webhook/instagram",
            content=body,
            headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.ig.sent, [])

    def test_valid_signature_confirms_and_processes(self):
        body = _message_body()

        response = self.client.post(
            "/webhook/instagram", content=body, headers={"X-Hub-Signature-256": _sign(body)}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.ig.sent), 1)
        self.assertEqual(self.ig.sent[0]["to"], IGSID)


class TestDuplicateDiscarded(IngressTestCase):
    """Requirement "Idempotência de entrega de webhook": a reentrega do mesmo
    evento é descartada sem erro."""

    def test_second_delivery_of_the_same_event_is_discarded_without_error(self):
        body = _message_body(message_id="dup-mid")

        first = self.client.post(
            "/webhook/instagram", content=body, headers={"X-Hub-Signature-256": _sign(body)}
        )
        second = self.client.post(
            "/webhook/instagram", content=body, headers={"X-Hub-Signature-256": _sign(body)}
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(self.ig.sent), 1, "a reentrega não deve gerar um segundo envio")


async def _build_request(body: bytes, headers: dict) -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/webhook/instagram",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "query_string": b"",
    }
    return Request(scope, receive)


class TestConfirmationHappensBeforeProcessing(IngressTestCase):
    """Task 4.3: proves the *order* of operations (confirmation, then
    processing) rather than measuring wall-clock time, which would be flaky.

    Calls the route function directly (bypassing `TestClient`, which would
    run the scheduled `BackgroundTasks` job for us and hide the ordering)
    to inspect the intermediate state: right after the handler returns its
    `Response`, the background job is *scheduled* but has not run yet — that
    is the same guarantee Starlette gives every real request (it sends the
    response body over ASGI before invoking any `BackgroundTasks`). Only
    after manually invoking the scheduled task does anything reach the
    channel client.
    """

    def test_processing_runs_only_after_the_response_is_built(self):
        body = _message_body(message_id="order-1")
        request = asyncio.run(_build_request(body, {"X-Hub-Signature-256": _sign(body)}))
        background_tasks = BackgroundTasks()

        response = asyncio.run(ingress.receive_webhook(request, background_tasks))

        # The response is already fully built (Starlette would already have
        # sent it over the wire at this point in a real request) — yet the
        # customer has not been answered.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(background_tasks.tasks), 1)
        self.assertEqual(self.ig.sent, [])
        self.assertEqual(self.db.contacts, {})

        # Only now, running the scheduled task exactly as Starlette would
        # after handing back the response, does processing happen.
        task = background_tasks.tasks[0]
        task.func(*task.args, **task.kwargs)

        self.assertEqual(len(self.ig.sent), 1)


class TestAsgiTransportOrderOfEvents(IngressTestCase):
    """Critic's own empirical proof (task 4.3 follow-up): `TestConfirmationHappensBeforeProcessing`
    only proves nothing runs before the *route function* returns — not that
    the HTTP response was actually sent over the ASGI transport before
    background processing runs. This drives the raw ASGI callable
    (`ingress.app(scope, receive, send)`) directly and instruments `send` to
    capture the real event sequence, exactly like the critic's repro."""

    def test_response_is_sent_over_the_wire_before_background_processing_runs(self):
        body = _message_body(message_id="asgi-order-1")
        events: list[str] = []

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            events.append(message["type"])

        original_process_event = ingress._process_event

        def _tracking_process_event(payload):
            events.append("PROCESSED_SEND")
            original_process_event(payload)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/webhook/instagram",
            "headers": [
                (b"x-hub-signature-256", _sign(body).encode("ascii")),
                (b"content-type", b"application/json"),
            ],
            "query_string": b"",
        }

        with patch.object(ingress, "_process_event", _tracking_process_event):
            asyncio.run(ingress.app(scope, receive, send))

        self.assertEqual(
            events,
            ["http.response.start", "http.response.body", "PROCESSED_SEND"],
        )
        self.assertEqual(len(self.ig.sent), 1)


class TestMalformedHeaderIsRejectedNotCrashed(IngressTestCase):
    """Critic BLOQUEADOR 3: Starlette decodes headers as latin-1, so a byte
    above 0x7F in `X-Hub-Signature-256` or `hub.verify_token` reaches
    `verify_signature`/`verify_handshake` as a non-ASCII `str`, which
    `hmac.compare_digest` cannot compare — it raises `TypeError` instead of
    just returning `False`, which used to propagate as an unhandled 500 on
    the exposed, unauthenticated endpoint."""

    def test_verify_signature_with_non_ascii_header_returns_false_not_raise(self):
        self.assertFalse(ingress.verify_signature("s", b"x", "sha256=" + "\xff"))

    def test_verify_handshake_with_non_ascii_token_returns_false_not_raise(self):
        self.assertFalse(
            ingress.verify_handshake("subscribe", "\xff\xfe", VERIFY_TOKEN)
        )

    def test_post_with_non_ascii_signature_header_gets_403_not_500(self):
        body = _message_body()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/webhook/instagram",
            "headers": [(b"x-hub-signature-256", b"sha256=\xff\xfe")],
            "query_string": b"",
        }
        request = Request(scope, receive)
        background_tasks = BackgroundTasks()

        response = asyncio.run(ingress.receive_webhook(request, background_tasks))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(background_tasks.tasks), 0)


class TestWhatsAppWebhook(IngressTestCase):
    """`whatsapp-cloud-channel-client`: same Meta handshake/signature
    protocol as Instagram (`verify_handshake`/`verify_signature` are
    product-agnostic, see `whatbot/ingress.py` module docstring), reused for
    the `/webhook/whatsapp` route added alongside `/webhook/instagram`."""

    def test_valid_token_echoes_the_challenge(self):
        response = self.client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": WA_VERIFY_TOKEN,
                "hub.challenge": "654321",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "654321")

    def test_invalid_token_is_rejected(self):
        response = self.client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "654321",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_missing_signature_is_rejected_and_nothing_is_processed(self):
        body = _wa_message_body()

        response = self.client.post(
            "/webhook/whatsapp", content=body, headers={"Content-Type": "application/json"}
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.wa.sent, [])
        self.assertEqual(self.db.contacts, {})

    def test_invalid_signature_is_rejected_and_nothing_is_processed(self):
        body = _wa_message_body()

        response = self.client.post(
            "/webhook/whatsapp",
            content=body,
            headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.wa.sent, [])

    def test_valid_signature_confirms_and_processes(self):
        body = _wa_message_body()

        response = self.client.post(
            "/webhook/whatsapp",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body, WA_SECRET)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.wa.sent), 1)
        self.assertEqual(self.wa.sent[0]["to"], WA_PHONE)

    def test_status_only_post_schedules_no_background_task(self):
        # A `statuses` batch (delivery/read ack) must not generate a reply —
        # see `whatbot/whatsapp_cloud_webhook.py` KIND_STATUS.
        body = _wa_status_body()
        request = asyncio.run(
            _build_request(body, {"X-Hub-Signature-256": _sign(body, WA_SECRET)})
        )
        background_tasks = BackgroundTasks()

        response = asyncio.run(ingress.receive_whatsapp_webhook(request, background_tasks))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(background_tasks.tasks), 0)
        self.assertEqual(self.wa.sent, [])

    def test_message_post_schedules_one_task_per_message(self):
        body = _wa_message_body()
        request = asyncio.run(
            _build_request(body, {"X-Hub-Signature-256": _sign(body, WA_SECRET)})
        )
        background_tasks = BackgroundTasks()

        response = asyncio.run(ingress.receive_whatsapp_webhook(request, background_tasks))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(background_tasks.tasks), 1)

    def test_second_delivery_of_the_same_event_is_discarded_without_error(self):
        body = _wa_message_body(message_id="wamid.dup")

        first = self.client.post(
            "/webhook/whatsapp",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body, WA_SECRET)},
        )
        second = self.client.post(
            "/webhook/whatsapp",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body, WA_SECRET)},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(self.wa.sent), 1, "a reentrega não deve gerar um segundo envio")


if __name__ == "__main__":
    unittest.main()
