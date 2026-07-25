"""Regression test: ProductSEOOptimizer (apps/shopify/seo/product_seo.py),
ShopifyFunnelEngine (apps/shopify/funnels/shopify_funnels.py), and
ShopifyAPIClient (apps/shopify/api_client.py) — three complete, honest
implementations sitting next to the already-wired Shopify Revenue Suite
(cart_recovery/flash_sale_engine/bundle_generator/product_recommender) but
never connected to aria_mind.py's dispatcher.

ProductSEOOptimizer and ShopifyFunnelEngine follow the same shape as the
already-wired engines (Redis-persisted, real ai_client.complete() calls with
a deterministic non-AI fallback, disclosed heuristic estimate fields like
seo_score/acceptance_rate_pct — never a fabricated "real" number).

ShopifyAPIClient is different: it's a REAL Shopify Admin API client
(SHOPIFY_SHOP_DOMAIN/SHOPIFY_ACCESS_TOKEN), gracefully degrading to a clear
"not configured" message rather than fabricating store data — the dashboard
tools before this were pure AI estimates with no path to real store numbers.

Wired into aria_mind.py's tool dispatcher as: optimize_product_seo,
audit_seo_keywords, create_upsell_offer, optimize_shopify_checkout,
create_post_purchase_flow, shopify_store_status, shopify_live_analytics
— plus seo/funnel stats folded into the existing shopify_revenue_dashboard.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engines directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.shopify.funnels.shopify_funnels import ShopifyFunnelEngine
from apps.shopify.seo.product_seo import ProductSEOOptimizer

pytestmark = pytest.mark.asyncio


class _FakeCache:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value
        return True


@pytest.fixture(autouse=True)
def _patch_caches():
    with (
        patch("apps.shopify.seo.product_seo.get_cache", return_value=_FakeCache()),
        patch("apps.shopify.funnels.shopify_funnels.get_cache", return_value=_FakeCache()),
    ):
        yield


# ── ProductSEOOptimizer ──────────────────────────────────────────────
async def test_optimize_product_seo_reachable_from_tool_dispatch():
    engine = ProductSEOOptimizer()
    with patch("apps.shopify.seo.product_seo.get_product_seo_optimizer", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "optimize_product_seo",
            {
                "product_id": "p1",
                "product_name": "Yoga Mat",
                "current_title": "Yoga Mat",
                "current_description": "A mat for yoga.",
                "category": "fitness",
            },
        )

    assert media == {}
    assert "SEO-optimized: Yoga Mat" in obs
    assert "score" in obs.lower()


async def test_optimize_product_seo_requires_name_and_title():
    mind = AriaMind()
    obs, media = await mind._execute_tool("optimize_product_seo", {})

    assert media == {}
    assert "title" in obs.lower()


async def test_audit_seo_keywords_reachable_from_tool_dispatch():
    engine = ProductSEOOptimizer()
    with patch("apps.shopify.seo.product_seo.get_product_seo_optimizer", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool("audit_seo_keywords", {"niche": "yoga mats"})

    assert media == {}
    assert "yoga mats" in obs
    assert "Commercial intent" in obs


async def test_audit_seo_keywords_requires_niche():
    mind = AriaMind()
    obs, media = await mind._execute_tool("audit_seo_keywords", {})

    assert media == {}
    assert "niche" in obs.lower()


# ── ShopifyFunnelEngine ───────────────────────────────────────────────
async def test_create_upsell_offer_reachable_from_tool_dispatch():
    engine = ShopifyFunnelEngine()
    with patch(
        "apps.shopify.funnels.shopify_funnels.get_shopify_funnel_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_upsell_offer",
            {
                "original_product": "Yoga Mat",
                "original_price": 40.0,
                "upsell_product": "Yoga Blocks",
                "upsell_price": 20.0,
            },
        )

    assert media == {}
    assert "Upsell offer" in obs


async def test_create_upsell_offer_requires_both_products():
    mind = AriaMind()
    obs, media = await mind._execute_tool("create_upsell_offer", {"original_product": "Yoga Mat"})

    assert media == {}
    assert "upsell product" in obs.lower()


async def test_optimize_shopify_checkout_reachable_from_tool_dispatch():
    engine = ShopifyFunnelEngine()
    with patch(
        "apps.shopify.funnels.shopify_funnels.get_shopify_funnel_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "optimize_shopify_checkout",
            {"product_name": "Yoga Mat", "pain_points": ["too many steps"]},
        )

    assert media == {}
    assert "Checkout optimization: Yoga Mat" in obs
    assert "too many steps" in obs


async def test_create_post_purchase_flow_reachable_from_tool_dispatch():
    engine = ShopifyFunnelEngine()
    with patch(
        "apps.shopify.funnels.shopify_funnels.get_shopify_funnel_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_post_purchase_flow", {"product_name": "Yoga Mat", "category": "fitness"}
        )

    assert media == {}
    assert "Post-purchase flow: Yoga Mat" in obs
    assert "review_request" in obs


# ── ShopifyAPIClient ──────────────────────────────────────────────────
async def test_shopify_store_status_not_configured():
    from apps.shopify.api_client import ShopifyAPIClient

    client = ShopifyAPIClient()
    client._domain = ""
    client._token = ""
    with patch("apps.shopify.api_client.get_shopify_api_client", return_value=client):
        mind = AriaMind()
        obs, media = await mind._execute_tool("shopify_store_status", {})

    assert media == {}
    assert "no shopify store connected" in obs.lower()


async def test_shopify_store_status_configured():
    from apps.shopify.api_client import ShopifyAPIClient

    client = ShopifyAPIClient()
    client._domain = "mystore.myshopify.com"
    client._token = "shpat_faketoken"
    with patch("apps.shopify.api_client.get_shopify_api_client", return_value=client):
        mind = AriaMind()
        obs, media = await mind._execute_tool("shopify_store_status", {})

    assert media == {}
    assert "Shopify store connected" in obs
    assert "myshopify.com" in obs
    assert "shpat_faketoken" not in obs  # never leak the token


async def test_shopify_live_analytics_requires_configured_store():
    from apps.shopify.api_client import ShopifyAPIClient

    client = ShopifyAPIClient()
    client._domain = ""
    client._token = ""
    with patch("apps.shopify.api_client.get_shopify_api_client", return_value=client):
        mind = AriaMind()
        obs, media = await mind._execute_tool("shopify_live_analytics", {})

    assert media == {}
    assert "no shopify store connected" in obs.lower()


async def test_shopify_live_analytics_reachable_when_configured():
    from unittest.mock import AsyncMock

    from apps.shopify.api_client import ShopifyAnalytics, ShopifyAPIClient

    client = ShopifyAPIClient()
    client._domain = "mystore.myshopify.com"
    client._token = "shpat_faketoken"
    client.get_revenue_analytics = AsyncMock(
        return_value=ShopifyAnalytics(
            period="last_30_days",
            total_revenue=1234.56,
            orders_count=10,
            avg_order_value=123.456,
            top_products=[{"product_id": "1", "title": "Yoga Mat", "revenue": 400.0}],
        )
    )
    with patch("apps.shopify.api_client.get_shopify_api_client", return_value=client):
        mind = AriaMind()
        obs, media = await mind._execute_tool("shopify_live_analytics", {"days": 30})

    assert media == {}
    assert "Real Shopify revenue" in obs
    assert "$1,234.56" in obs
    assert "Yoga Mat" in obs
    client.get_revenue_analytics.assert_awaited_once_with(30)


# ── shopify_revenue_dashboard now folds in SEO + funnel stats ─────────
async def test_shopify_revenue_dashboard_includes_seo_and_funnel_stats():
    from apps.shopify.bundles.bundle_generator import BundleGenerator
    from apps.shopify.offers.flash_sale_engine import FlashSaleEngine
    from apps.shopify.revenue.cart_recovery import CartRecoveryEngine
    from apps.shopify.revenue.product_recommender import ProductRecommender

    with (
        patch(
            "apps.shopify.revenue.cart_recovery.get_cart_recovery_engine",
            return_value=CartRecoveryEngine(),
        ),
        patch(
            "apps.shopify.offers.flash_sale_engine.get_flash_sale_engine",
            return_value=FlashSaleEngine(),
        ),
        patch(
            "apps.shopify.bundles.bundle_generator.get_bundle_generator",
            return_value=BundleGenerator(),
        ),
        patch(
            "apps.shopify.revenue.product_recommender.get_product_recommender",
            return_value=ProductRecommender(),
        ),
        patch(
            "apps.shopify.seo.product_seo.get_product_seo_optimizer",
            return_value=ProductSEOOptimizer(),
        ),
        patch(
            "apps.shopify.funnels.shopify_funnels.get_shopify_funnel_engine",
            return_value=ShopifyFunnelEngine(),
        ),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("shopify_revenue_dashboard", {})

    assert media == {}
    assert "SEO:" in obs
    assert "Funnels:" in obs
