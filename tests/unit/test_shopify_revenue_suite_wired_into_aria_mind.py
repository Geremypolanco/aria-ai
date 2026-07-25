"""Regression test: the Shopify Revenue Suite — CartRecoveryEngine,
FlashSaleEngine, BundleGenerator, ProductRecommender (all under apps/shopify/)
— four complete implementations with their own singleton getters had zero
live callers. Found via a full-repo audit (an agent scanned ~130 get_X()
singletons for genuinely dead, complete, non-redundant, honest engines).

Wired into aria_mind.py's tool dispatcher as: recover_abandoned_cart,
create_flash_sale, create_product_bundle, recommend_products,
shopify_revenue_dashboard.

A later security-audit pass found these wrote to Redis keys shared by ALL
users (shopify:flash_sales:v1, shopify:bundles:v1, ...) with no ownership
check — any signed-in non-owner user could create real sales/bundles
against "the store" or read the owner's cart-recovery/recommendation data.
They're now owner-only (_OWNER_ONLY_TOOLS), so every test below runs as
the owner.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engines directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.shopify.bundles.bundle_generator import BundleGenerator
from apps.shopify.offers.flash_sale_engine import FlashSaleEngine
from apps.shopify.revenue.cart_recovery import CartRecoveryEngine
from apps.shopify.revenue.product_recommender import ProductRecommender

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
def _patch_caches_and_owner():
    with (
        patch(
            "apps.shopify.revenue.cart_recovery.get_cache",
            return_value=_FakeCache(),
        ),
        patch(
            "apps.shopify.offers.flash_sale_engine.get_cache",
            return_value=_FakeCache(),
        ),
        patch(
            "apps.shopify.bundles.bundle_generator.get_cache",
            return_value=_FakeCache(),
        ),
        patch(
            "apps.shopify.revenue.product_recommender.get_cache",
            return_value=_FakeCache(),
        ),
        patch("apps.core.auth.is_owner_email", side_effect=lambda e: e == OWNER_EMAIL),
    ):
        yield


async def test_shopify_revenue_tools_blocked_for_non_owner():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "recover_abandoned_cart", {"email": "x@example.com", "items": []}, email="someone@else.com"
    )

    assert media == {}
    assert "owner" in obs.lower()


async def test_recover_abandoned_cart_reachable_from_tool_dispatch():
    engine = CartRecoveryEngine()
    with patch("apps.shopify.revenue.cart_recovery.get_cart_recovery_engine", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "recover_abandoned_cart",
            {
                "email": "shopper@example.com",
                "items": [{"title": "Yoga Mat", "price": 40.0}],
                "cart_value": 40.0,
            },
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "shopper@example.com" in obs
    assert "+24h" in obs and "+72h" in obs


async def test_recover_abandoned_cart_requires_email_and_items():
    mind = AriaMind()
    obs, media = await mind._execute_tool("recover_abandoned_cart", {}, email=OWNER_EMAIL)

    assert media == {}
    assert "email" in obs.lower()


async def test_create_flash_sale_reachable_from_tool_dispatch():
    engine = FlashSaleEngine()
    with patch("apps.shopify.offers.flash_sale_engine.get_flash_sale_engine", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_flash_sale",
            {
                "name": "Weekend Blowout",
                "products": [{"id": "p1", "title": "Yoga Mat", "price": 40.0}],
                "discount_pct": 0.25,
                "duration_hours": 12,
            },
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "Weekend Blowout" in obs
    assert "25%" in obs


async def test_create_product_bundle_reachable_from_tool_dispatch():
    engine = BundleGenerator()
    with patch("apps.shopify.bundles.bundle_generator.get_bundle_generator", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_product_bundle",
            {
                "products": [
                    {"id": "p1", "title": "Yoga Mat", "price": 40.0},
                    {"id": "p2", "title": "Yoga Blocks", "price": 20.0},
                ],
                "bundle_type": "complementary",
                "discount_pct": 0.15,
            },
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "$60.00" in obs or "$51.00" in obs  # individual total / bundle price shown


async def test_create_product_bundle_requires_two_products():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "create_product_bundle",
        {"products": [{"id": "p1", "title": "Solo", "price": 10.0}]},
        email=OWNER_EMAIL,
    )

    assert media == {}
    assert "2 products" in obs


async def test_recommend_products_reachable_from_tool_dispatch():
    engine = ProductRecommender()
    with patch(
        "apps.shopify.revenue.product_recommender.get_product_recommender", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "recommend_products",
            {
                "user_id": "u1",
                "context": "homepage",
                "catalog": [
                    {"id": "p1", "title": "Yoga Mat", "price": 40.0, "category": "fitness"},
                    {"id": "p2", "title": "Yoga Blocks", "price": 20.0, "category": "fitness"},
                ],
            },
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "Recommendations" in obs


async def test_shopify_revenue_dashboard_reachable_from_tool_dispatch():
    cart_engine = CartRecoveryEngine()
    sale_engine = FlashSaleEngine()
    bundle_engine = BundleGenerator()
    rec_engine = ProductRecommender()
    with (
        patch(
            "apps.shopify.revenue.cart_recovery.get_cart_recovery_engine",
            return_value=cart_engine,
        ),
        patch(
            "apps.shopify.offers.flash_sale_engine.get_flash_sale_engine",
            return_value=sale_engine,
        ),
        patch(
            "apps.shopify.bundles.bundle_generator.get_bundle_generator",
            return_value=bundle_engine,
        ),
        patch(
            "apps.shopify.revenue.product_recommender.get_product_recommender",
            return_value=rec_engine,
        ),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("shopify_revenue_dashboard", {}, email=OWNER_EMAIL)

    assert media == {}
    assert "Shopify revenue dashboard" in obs
    assert "Cart recovery" in obs
    assert "Flash sales" in obs
    assert "Bundles" in obs
