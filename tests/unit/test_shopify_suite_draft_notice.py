"""Regression test: the Shopify Revenue Suite (cart recovery, flash sales,
bundles, SEO, upsells, checkout optimization, post-purchase flows) generates
real AI strategy and copy but never calls the actual Shopify API — confirmed
via grep, none of these engine modules import ShopifyAPIClient/
get_shopify_api_client. Tool responses like "Flash sale 'X' created" or
"SEO-optimized: Y" used to read as if a real discount code, product update,
or price change had been applied to the live store, when nothing was. Every
tool in this suite that implies a store-side action now appends
_SHOPIFY_DRAFT_NOTICE so the user isn't misled into thinking it's already live.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engines directly."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.core.cognition.aria_mind import AriaMind, _SHOPIFY_DRAFT_NOTICE
from apps.shopify.bundles.bundle_generator import BundleGenerator
from apps.shopify.funnels.shopify_funnels import ShopifyFunnelEngine
from apps.shopify.offers.flash_sale_engine import FlashSaleEngine
from apps.shopify.revenue.cart_recovery import CartRecoveryEngine
from apps.shopify.seo.product_seo import ProductSEOOptimizer

pytestmark = pytest.mark.asyncio

OWNER_EMAIL = "owner@aria.test"


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
        patch("apps.shopify.revenue.cart_recovery.get_cache", return_value=_FakeCache()),
        patch("apps.shopify.offers.flash_sale_engine.get_cache", return_value=_FakeCache()),
        patch("apps.shopify.bundles.bundle_generator.get_cache", return_value=_FakeCache()),
        patch("apps.shopify.seo.product_seo.get_cache", return_value=_FakeCache()),
        patch("apps.shopify.funnels.shopify_funnels.get_cache", return_value=_FakeCache()),
        patch("apps.core.auth.is_owner_email", side_effect=lambda e: e == OWNER_EMAIL),
    ):
        yield


async def test_recover_abandoned_cart_carries_draft_notice():
    engine = CartRecoveryEngine()
    with patch("apps.shopify.revenue.cart_recovery.get_cart_recovery_engine", return_value=engine):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "recover_abandoned_cart",
            {
                "email": "shopper@example.com",
                "items": [{"title": "Yoga Mat", "price": 40.0}],
                "cart_value": 40.0,
            },
            email=OWNER_EMAIL,
        )
    assert _SHOPIFY_DRAFT_NOTICE.strip() in obs


async def test_create_flash_sale_carries_draft_notice():
    engine = FlashSaleEngine()
    with patch("apps.shopify.offers.flash_sale_engine.get_flash_sale_engine", return_value=engine):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "create_flash_sale",
            {
                "name": "Weekend Blowout",
                "products": [{"id": "p1", "title": "Yoga Mat", "price": 40.0}],
                "discount_pct": 0.25,
            },
            email=OWNER_EMAIL,
        )
    assert _SHOPIFY_DRAFT_NOTICE.strip() in obs


async def test_create_product_bundle_carries_draft_notice():
    engine = BundleGenerator()
    with patch("apps.shopify.bundles.bundle_generator.get_bundle_generator", return_value=engine):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "create_product_bundle",
            {
                "products": [
                    {"id": "p1", "title": "Yoga Mat", "price": 40.0},
                    {"id": "p2", "title": "Yoga Blocks", "price": 20.0},
                ]
            },
            email=OWNER_EMAIL,
        )
    assert _SHOPIFY_DRAFT_NOTICE.strip() in obs


async def test_optimize_product_seo_carries_draft_notice():
    engine = ProductSEOOptimizer()
    with patch("apps.shopify.seo.product_seo.get_product_seo_optimizer", return_value=engine):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "optimize_product_seo",
            {
                "product_id": "p1",
                "product_name": "Yoga Mat",
                "current_title": "Yoga Mat",
                "current_description": "A mat for yoga.",
                "category": "fitness",
            },
            email=OWNER_EMAIL,
        )
    assert _SHOPIFY_DRAFT_NOTICE.strip() in obs


async def test_create_upsell_offer_carries_draft_notice():
    engine = ShopifyFunnelEngine()
    with patch(
        "apps.shopify.funnels.shopify_funnels.get_shopify_funnel_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "create_upsell_offer",
            {
                "original_product": "Yoga Mat",
                "original_price": 40.0,
                "upsell_product": "Yoga Blocks",
                "upsell_price": 20.0,
            },
            email=OWNER_EMAIL,
        )
    assert _SHOPIFY_DRAFT_NOTICE.strip() in obs


async def test_optimize_shopify_checkout_carries_draft_notice():
    engine = ShopifyFunnelEngine()
    with patch(
        "apps.shopify.funnels.shopify_funnels.get_shopify_funnel_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "optimize_shopify_checkout",
            {"product_name": "Yoga Mat", "pain_points": ["too many steps"]},
            email=OWNER_EMAIL,
        )
    assert _SHOPIFY_DRAFT_NOTICE.strip() in obs


async def test_create_post_purchase_flow_carries_draft_notice():
    engine = ShopifyFunnelEngine()
    with patch(
        "apps.shopify.funnels.shopify_funnels.get_shopify_funnel_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, _ = await mind._execute_tool(
            "create_post_purchase_flow",
            {"product_name": "Yoga Mat", "category": "fitness"},
            email=OWNER_EMAIL,
        )
    assert _SHOPIFY_DRAFT_NOTICE.strip() in obs
