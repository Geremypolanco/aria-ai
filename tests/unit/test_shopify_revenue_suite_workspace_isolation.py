"""Multi-tenancy conversion of the Shopify Revenue Suite — the six engines
behind recover_abandoned_cart, create_flash_sale, create_product_bundle,
recommend_products, optimize_product_seo/audit_seo_keywords, and
create_upsell_offer/optimize_shopify_checkout/create_post_purchase_flow.

Unlike apps/shopify/api_client.py (which needs real per-workspace Shopify
credentials — see test_shopify_workspace_credentials.py), these six engines
never call the real Shopify API at all: they're pure Redis-backed
AI-estimate bookkeeping, structurally identical to CashflowEngine/
ROITracker. Each used to persist to ONE hardcoded global Redis key
regardless of caller — this converts them to the same per-workspace-key +
narrowly-scoped legacy-owner-fallback pattern already established there.

The critical case under test for every engine, mirroring CashflowEngine's:
a brand-new workspace's empty state must read as empty, NEVER inheriting
whatever the real owner's pre-multi-tenancy global data happened to contain
— that fallback applies ONLY to the actual configured owner's own
workspace_id.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.shopify.bundles.bundle_generator import BundleGenerator, get_bundle_generator
from apps.shopify.funnels.shopify_funnels import ShopifyFunnelEngine, get_shopify_funnel_engine
from apps.shopify.offers.flash_sale_engine import FlashSaleEngine, get_flash_sale_engine
from apps.shopify.revenue.cart_recovery import CartRecoveryEngine, get_cart_recovery_engine
from apps.shopify.revenue.product_recommender import ProductRecommender, get_product_recommender
from apps.shopify.seo.product_seo import ProductSEOOptimizer, get_product_seo_optimizer

pytestmark = pytest.mark.asyncio


def _mock_cache(get_return=None):
    c = MagicMock()
    c.get = AsyncMock(return_value=get_return)
    c.set = AsyncMock(return_value=True)
    return c


# Each entry: (EngineClass, get_engine_fn, module path for patching get_cache/
# auth.owner_emails, legacy key, sample "own data" payload, path to read
# back the loaded state from the instance for assertion).
ENGINES = [
    pytest.param(
        CartRecoveryEngine,
        get_cart_recovery_engine,
        "apps.shopify.revenue.cart_recovery",
        "shopify:cart_recovery:v1",
        [{"cart_id": "c1"}],
        lambda e: e._carts,
        id="CartRecoveryEngine",
    ),
    pytest.param(
        FlashSaleEngine,
        get_flash_sale_engine,
        "apps.shopify.offers.flash_sale_engine",
        "shopify:flash_sales:v1",
        [{"sale_id": "s1"}],
        lambda e: e._sales,
        id="FlashSaleEngine",
    ),
    pytest.param(
        BundleGenerator,
        get_bundle_generator,
        "apps.shopify.bundles.bundle_generator",
        "shopify:bundles:v1",
        [{"bundle_id": "b1"}],
        lambda e: e._bundles,
        id="BundleGenerator",
    ),
    pytest.param(
        ShopifyFunnelEngine,
        get_shopify_funnel_engine,
        "apps.shopify.funnels.shopify_funnels",
        "shopify:funnels:v1",
        {"funnels": [{"funnel_id": "f1"}], "upsells": []},
        lambda e: e._funnels,
        id="ShopifyFunnelEngine",
    ),
    pytest.param(
        ProductSEOOptimizer,
        get_product_seo_optimizer,
        "apps.shopify.seo.product_seo",
        "shopify:seo:v1",
        {"optimizations": [{"seo_id": "o1"}]},
        lambda e: e._optimizations,
        id="ProductSEOOptimizer",
    ),
    pytest.param(
        ProductRecommender,
        get_product_recommender,
        "apps.shopify.revenue.product_recommender",
        "shopify:recommendations:v1",
        {"interactions": {"u1": ["p1"]}, "popularity": {"p1": 1}},
        lambda e: e._interaction_data,
        id="ProductRecommender",
    ),
]


@pytest.mark.parametrize(
    "engine_cls,get_engine,module_path,legacy_key,legacy_payload,read_state", ENGINES
)
class TestShopifyRevenueSuiteWorkspaceIsolation:
    def test_two_workspaces_never_share_a_cache_key(
        self, engine_cls, get_engine, module_path, legacy_key, legacy_payload, read_state
    ):
        engine_a = engine_cls("workspace-a@example.com")
        engine_b = engine_cls("workspace-b@example.com")
        assert engine_a._cache_key != engine_b._cache_key
        assert "workspace-a@example.com" in engine_a._cache_key
        assert "workspace-b@example.com" in engine_b._cache_key

    def test_get_engine_returns_distinct_instances_per_workspace(
        self, engine_cls, get_engine, module_path, legacy_key, legacy_payload, read_state
    ):
        engine_a = get_engine("workspace-a@example.com")
        engine_b = get_engine("workspace-b@example.com")
        assert engine_a is not engine_b
        assert get_engine("workspace-a@example.com") is engine_a

    async def test_non_owner_workspace_never_inherits_the_legacy_data(
        self, engine_cls, get_engine, module_path, legacy_key, legacy_payload, read_state
    ):
        cache = _mock_cache()

        async def fake_get(key):
            if key == legacy_key:
                return legacy_payload
            return None

        cache.get = AsyncMock(side_effect=fake_get)

        with (
            patch(f"{module_path}.get_cache", return_value=cache),
            patch("apps.core.auth.owner_emails", return_value={"real-owner@example.com"}),
        ):
            engine = engine_cls("brand-new-team@example.com")
            await engine._load()

        state = read_state(engine)
        assert not state  # empty dict or empty list, never the owner's legacy data

    async def test_the_real_owners_own_workspace_inherits_the_legacy_data_once(
        self, engine_cls, get_engine, module_path, legacy_key, legacy_payload, read_state
    ):
        cache = _mock_cache()

        async def fake_get(key):
            if key == legacy_key:
                return legacy_payload
            return None

        cache.get = AsyncMock(side_effect=fake_get)

        with (
            patch(f"{module_path}.get_cache", return_value=cache),
            patch("apps.core.auth.owner_emails", return_value={"real-owner@example.com"}),
        ):
            engine = engine_cls("real-owner@example.com")
            await engine._load()

        state = read_state(engine)
        assert state  # non-empty — the owner's legacy data carried forward
