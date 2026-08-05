"""Tests for the WhatsApp channel client.

The class was moved between modules and gained a `human_agent` kwarg in the
channels refactor without a single test covering it — not the request it builds,
not the outbound logging, not the failure path.
"""

import unittest
from unittest.mock import MagicMock, patch

import requests

from whatbot.channels import WHATSAPP
from whatbot.channels.whatsapp_evolution import EvolutionApiClient

PHONE = "5511999999999"


def build_client() -> EvolutionApiClient:
    return EvolutionApiClient(
        api_key="secret-key",
        instance_name="whatbot",
        base_url="http://evolution-api:8080/",
    )


class TestClientContract(unittest.TestCase):
    def test_declares_its_channel(self):
        self.assertEqual(EvolutionApiClient.canal, WHATSAPP)

    def test_base_url_trailing_slash_is_stripped(self):
        self.assertEqual(build_client().base_url, "http://evolution-api:8080")


class TestSend(unittest.TestCase):
    def setUp(self):
        self.client = build_client()
        self.response = MagicMock(ok=True)
        self.response.json.return_value = {"key": {"id": "MSG1"}}

        post_patch = patch(
            "whatbot.channels.whatsapp_evolution.requests.post",
            return_value=self.response,
        )
        log_patch = patch("whatbot.channels.whatsapp_evolution.log_outbound")
        self.post = post_patch.start()
        self.log_outbound = log_patch.start()
        self.addCleanup(post_patch.stop)
        self.addCleanup(log_patch.stop)

    def test_builds_the_expected_request(self):
        self.client.send_text(PHONE, "Olá")

        url, = self.post.call_args.args
        kwargs = self.post.call_args.kwargs
        self.assertEqual(url, "http://evolution-api:8080/message/sendText/whatbot")
        self.assertEqual(kwargs["headers"]["apikey"], "secret-key")
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(kwargs["json"], {"number": PHONE, "text": "Olá"})
        self.assertEqual(kwargs["timeout"], 10)

    def test_returns_the_api_response(self):
        result = self.client.send_text(PHONE, "Olá")

        self.assertEqual(result, {"key": {"id": "MSG1"}})

    def test_human_agent_is_accepted_and_ignored(self):
        """WhatsApp has no messaging window; the kwarg must not alter the payload."""
        self.client.send_text(PHONE, "Olá", human_agent=True)

        self.assertEqual(self.post.call_args.kwargs["json"], {"number": PHONE, "text": "Olá"})

    def test_successful_send_is_logged_as_sent(self):
        self.client.send_text(PHONE, "Olá", source="handover", contact_id=7)

        self.log_outbound.assert_called_once()
        args, kwargs = self.log_outbound.call_args
        self.assertEqual(args, (PHONE, "Olá"))
        self.assertEqual(kwargs["delivery"], "sent")
        self.assertEqual(kwargs["source"], "handover")
        self.assertEqual(kwargs["contact_id"], 7)


class TestSimulation(unittest.TestCase):
    def setUp(self):
        post_patch = patch("whatbot.channels.whatsapp_evolution.requests.post")
        log_patch = patch("whatbot.channels.whatsapp_evolution.log_outbound")
        self.post = post_patch.start()
        self.log_outbound = log_patch.start()
        self.addCleanup(post_patch.stop)
        self.addCleanup(log_patch.stop)

    def test_simulated_send_never_touches_the_network(self):
        result = build_client().send_text(PHONE, "Olá", simulated=True)

        self.post.assert_not_called()
        self.assertEqual(result, {"simulated": True})

    def test_simulated_send_is_logged_as_skipped(self):
        build_client().send_text(PHONE, "Olá", simulated=True)

        kwargs = self.log_outbound.call_args.kwargs
        self.assertEqual(kwargs["delivery"], "skipped")
        self.assertTrue(kwargs["simulated"])


class TestFetchCatalog(unittest.TestCase):
    """catalog-product-sync: `EvolutionApiClient.fetch_catalog`."""

    def setUp(self):
        self.client = build_client()

    def test_builds_the_expected_request(self):
        response = MagicMock(ok=True)
        response.json.return_value = []

        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post",
            return_value=response,
        ) as post:
            self.client.fetch_catalog()

        url, = post.call_args.args
        kwargs = post.call_args.kwargs
        self.assertEqual(url, "http://evolution-api:8080/chat/fetchCatalogs/whatbot")
        self.assertEqual(kwargs["headers"]["apikey"], "secret-key")
        self.assertEqual(kwargs["timeout"], 10)

    def test_maps_raw_catalog_items_to_the_local_schema(self):
        response = MagicMock(ok=True)
        response.json.return_value = [
            {"id": "PROD-1", "name": "Camiseta", "price": 4990, "isHidden": False},
            {"id": "PROD-2", "name": "Boné", "price": 2990, "isHidden": True},
        ]

        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post",
            return_value=response,
        ):
            products = self.client.fetch_catalog()

        self.assertEqual(
            products,
            [
                {
                    "product_id": "PROD-1",
                    "nome": "Camiseta",
                    "preco": 4990,
                    "disponivel": True,
                },
                {
                    "product_id": "PROD-2",
                    "nome": "Boné",
                    "preco": 2990,
                    "disponivel": False,
                },
            ],
        )

    def test_response_wrapped_in_a_catalog_key_is_also_accepted(self):
        response = MagicMock(ok=True)
        response.json.return_value = {
            "catalog": [{"id": "PROD-1", "name": "Camiseta", "price": 4990}]
        }

        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post",
            return_value=response,
        ):
            products = self.client.fetch_catalog()

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["product_id"], "PROD-1")

    def test_item_without_a_recognizable_id_is_dropped_others_still_persisted(self):
        """Critic feedback (catalog-product-sync): a malformed item must not
        cost every other valid product in the same response — and must not
        surface as `product_id=None` reaching `Database.upsert_catalog_products`,
        which would violate the `PRIMARY KEY NOT NULL` constraint."""
        response = MagicMock(ok=True)
        response.json.return_value = [
            {"id": "PROD-1", "name": "Camiseta", "price": 4990},
            {"name": "Sem id reconhecível", "price": 1000},
        ]

        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post",
            return_value=response,
        ):
            products = self.client.fetch_catalog()

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["product_id"], "PROD-1")

    def test_non_dict_item_in_the_raw_list_is_dropped_not_raised(self):
        """A non-dict raw item must not raise `AttributeError` — the whole
        point of moving normalization inside the `try` is that only
        `requests.RequestException` propagates out of `fetch_catalog`."""
        response = MagicMock(ok=True)
        response.json.return_value = [
            {"id": "PROD-1", "name": "Camiseta", "price": 4990},
            "not-a-product-dict",
            None,
            42,
        ]

        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post",
            return_value=response,
        ):
            products = self.client.fetch_catalog()

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["product_id"], "PROD-1")

    def test_network_failure_propagates(self):
        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post",
            side_effect=requests.ConnectionError("sem rede"),
        ):
            with self.assertRaises(requests.RequestException):
                self.client.fetch_catalog()

    def test_http_error_response_propagates(self):
        response = MagicMock(ok=False, status_code=500, text="erro interno")
        response.raise_for_status.side_effect = requests.HTTPError("500")

        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post",
            return_value=response,
        ):
            with self.assertRaises(requests.RequestException):
                self.client.fetch_catalog()


class TestFailure(unittest.TestCase):
    def setUp(self):
        log_patch = patch("whatbot.channels.whatsapp_evolution.log_outbound")
        self.log_outbound = log_patch.start()
        self.addCleanup(log_patch.stop)

    def test_transport_failure_is_logged_as_failed(self):
        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post",
            side_effect=requests.ConnectionError("sem rede"),
        ):
            with self.assertRaises(Exception):
                build_client().send_text(PHONE, "Olá")

        kwargs = self.log_outbound.call_args.kwargs
        self.assertEqual(kwargs["delivery"], "failed")
        self.assertIn("sem rede", kwargs["error"])

    def test_http_error_response_raises(self):
        response = MagicMock(ok=False, status_code=401, text="unauthorized")
        response.raise_for_status.side_effect = requests.HTTPError("401")

        with patch(
            "whatbot.channels.whatsapp_evolution.requests.post", return_value=response
        ):
            with self.assertRaises(Exception):
                build_client().send_text(PHONE, "Olá")

        self.assertEqual(self.log_outbound.call_args.kwargs["delivery"], "failed")


if __name__ == "__main__":
    unittest.main()
