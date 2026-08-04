"""catalog-product-sync: upsert idempotente de `produtos_catalogo`, resolução
parcial de itens, e o job de sincronização (`whatbot.main.sync_catalog`).

`Database.upsert_catalog_products`/`resolve_catalog_items` só têm implementação
real contra Postgres (`whatbot/db.py`) — sem rede/Postgres nos testes
unitários (ver `openspec/project.md`), então este arquivo exercita o
comportamento via `FakeDatabase` (`tests/fakes.py`), mesma convenção do resto
da suíte.
"""

import unittest
from unittest.mock import MagicMock, patch

from whatbot import main as main_mod
from whatbot.channels import WHATSAPP, ChannelRouter
from whatbot.channels.whatsapp_evolution import EvolutionApiClient

from fakes import FakeDatabase

CATALOG = [
    {"product_id": "PROD-1", "nome": "Camiseta", "preco": 49.9, "disponivel": True},
    {"product_id": "PROD-2", "nome": "Boné", "preco": 29.9, "disponivel": False},
]


class FakeCatalogClient:
    """Minimal WhatsApp channel client exposing only `fetch_catalog`."""

    canal = WHATSAPP

    def __init__(self, products=None, error: Exception | None = None):
        self._products = products or []
        self._error = error
        self.calls = 0

    def fetch_catalog(self):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._products

    def send_text(self, *args, **kwargs):  # pragma: no cover - not exercised here
        raise NotImplementedError


class TestUpsertCatalogProductsIsIdempotent(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()

    def test_running_twice_does_not_duplicate_rows(self):
        self.db.upsert_catalog_products(CATALOG)
        self.db.upsert_catalog_products(CATALOG)

        self.assertEqual(len(self.db.catalog_products), 2)

    def test_running_twice_refreshes_last_synced_at(self):
        self.db.upsert_catalog_products(CATALOG)
        first_sync = self.db.catalog_products["PROD-1"]["last_synced_at"]

        self.db.upsert_catalog_products(CATALOG)
        second_sync = self.db.catalog_products["PROD-1"]["last_synced_at"]

        self.assertGreaterEqual(second_sync, first_sync)

    def test_conflicting_upsert_updates_the_existing_product(self):
        self.db.upsert_catalog_products(CATALOG)

        self.db.upsert_catalog_products(
            [{"product_id": "PROD-1", "nome": "Camiseta P", "preco": 39.9, "disponivel": False}]
        )

        updated = self.db.catalog_products["PROD-1"]
        self.assertEqual(updated["nome"], "Camiseta P")
        self.assertEqual(updated["preco"], 39.9)
        self.assertFalse(updated["disponivel"])
        # Product not touched by the second call keeps its previous data.
        self.assertEqual(self.db.catalog_products["PROD-2"]["nome"], "Boné")


class TestResolveCatalogItems(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.db.upsert_catalog_products(CATALOG)

    def test_resolves_known_items(self):
        result = self.db.resolve_catalog_items(["PROD-1", "PROD-2"])

        self.assertEqual({item["product_id"] for item in result}, {"PROD-1", "PROD-2"})

    def test_unknown_id_is_omitted_without_raising(self):
        result = self.db.resolve_catalog_items(["PROD-1", "PROD-UNKNOWN"])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["product_id"], "PROD-1")

    def test_empty_list_returns_empty_list(self):
        self.assertEqual(self.db.resolve_catalog_items([]), [])


class TestSyncCatalogJob(unittest.TestCase):
    """`whatbot.main.sync_catalog()` — the function the Windmill job
    (`windmill/f/whatbot/sync_catalog.py`) delegates to."""

    def setUp(self):
        self.db = FakeDatabase()
        patches = [
            patch.object(main_mod, "_db", self.db),
            patch.object(main_mod, "_init_infra", lambda: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_successful_sync_upserts_the_catalog(self):
        client = FakeCatalogClient(products=CATALOG)
        router = ChannelRouter([client])

        with patch.object(main_mod, "_router", router):
            result = main_mod.sync_catalog()

        self.assertTrue(result["ok"])
        self.assertEqual(result["synced"], 2)
        self.assertEqual(client.calls, 1)
        self.assertEqual(len(self.db.catalog_products), 2)

    def test_fetch_failure_does_not_raise_and_reports_failure(self):
        failing_client = FakeCatalogClient(error=ConnectionError("sem rede"))
        router = ChannelRouter([failing_client])

        with patch.object(main_mod, "_router", router):
            result = main_mod.sync_catalog()  # must not raise

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "fetch_catalog_failed")

    def test_fetch_failure_leaves_the_previous_cache_untouched(self):
        self.db.upsert_catalog_products(CATALOG)
        failing_client = FakeCatalogClient(error=ConnectionError("sem rede"))
        router = ChannelRouter([failing_client])

        with patch.object(main_mod, "_router", router):
            main_mod.sync_catalog()

        self.assertEqual(len(self.db.catalog_products), 2)
        self.assertEqual(self.db.catalog_products["PROD-1"]["nome"], "Camiseta")

    def test_upsert_failure_does_not_raise_and_reports_failure(self):
        """Critic feedback (catalog-product-sync, bloqueador): a malformed
        product (e.g. `product_id=None`) reaching `upsert_catalog_products`
        used to roll back the whole batch and propagate uncaught out of
        `sync_catalog()`, contradicting its own docstring. Persistence
        failures must be caught exactly like fetch failures."""
        self.db.upsert_catalog_products(CATALOG)  # a prior successful sync

        def _boom(products):
            raise RuntimeError("product_id=None viola PRIMARY KEY NOT NULL")

        self.db.upsert_catalog_products = _boom  # type: ignore[method-assign]
        client = FakeCatalogClient(products=[{"product_id": None, "nome": "Ruim"}])
        router = ChannelRouter([client])

        with patch.object(main_mod, "_router", router):
            result = main_mod.sync_catalog()  # must not raise

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "upsert_failed")


class TestSyncCatalogJobWithTheRealClient(unittest.TestCase):
    """End-to-end through `EvolutionApiClient.fetch_catalog` (mocked HTTP)
    into `sync_catalog()`, so the normalization/filtering that lives in
    `whatsapp_evolution.py` is exercised together with the job, not just in
    isolation."""

    def setUp(self):
        self.db = FakeDatabase()
        patches = [
            patch.object(main_mod, "_db", self.db),
            patch.object(main_mod, "_init_infra", lambda: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_a_malformed_item_is_dropped_but_valid_products_are_still_persisted(self):
        response = MagicMock(ok=True)
        response.json.return_value = [
            {"id": "PROD-1", "name": "Camiseta", "price": 4990},
            {"name": "Sem id reconhecível", "price": 1000},
            "not-a-product-dict",
        ]
        client = EvolutionApiClient(
            api_key="secret-key", instance_name="whatbot", base_url="http://evolution-api:8080"
        )
        router = ChannelRouter([client])

        with patch.object(main_mod, "_router", router), patch(
            "whatbot.channels.whatsapp_evolution.requests.post", return_value=response
        ):
            result = main_mod.sync_catalog()  # must not raise

        self.assertTrue(result["ok"])
        self.assertEqual(result["synced"], 1)
        self.assertEqual(len(self.db.catalog_products), 1)
        self.assertEqual(self.db.catalog_products["PROD-1"]["nome"], "Camiseta")


if __name__ == "__main__":
    unittest.main()
