"""Regression test: LandingPageEngine (apps/conversion/landing_pages/) and
PricingIntelligence (apps/market/pricing/) — complete implementations with
their own singleton getters — had zero live callers. Continuing the batch
from the full-repo dead-code audit (Shopify Revenue Suite, then lead
discovery/LinkedIn outreach, now landing pages/pricing).

Wired into aria_mind.py's tool dispatcher as: create_landing_page,
generate_landing_headlines, landing_page_stats, analyze_pricing,
suggest_dynamic_price, build_pricing_strategy, pricing_dashboard.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engines directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.conversion.landing_pages.landing_page_engine import LandingPageEngine
from apps.core.cognition.aria_mind import AriaMind
from apps.market.pricing.pricing_intelligence import PricingIntelligence

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
        patch(
            "apps.conversion.landing_pages.landing_page_engine.get_cache",
            return_value=_FakeCache(),
        ),
        patch("apps.market.pricing.pricing_intelligence.get_cache", return_value=_FakeCache()),
    ):
        yield


async def test_create_landing_page_reachable_from_tool_dispatch():
    engine = LandingPageEngine()
    with patch(
        "apps.conversion.landing_pages.landing_page_engine.get_landing_page_engine",
        return_value=engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_landing_page",
            {
                "product": "Yoga Mat Pro",
                "offer": "20% off launch week",
                "target_audience": "home fitness enthusiasts",
                "price": 49.0,
            },
        )

    assert media == {}
    assert "Yoga Mat Pro" in obs or "Get Yoga Mat Pro" in obs
    assert "Placeholder numbers" in obs


async def test_create_landing_page_requires_product_and_offer():
    mind = AriaMind()
    obs, media = await mind._execute_tool("create_landing_page", {})

    assert media == {}
    assert "product" in obs.lower()


async def test_generate_landing_headlines_reachable_from_tool_dispatch():
    engine = LandingPageEngine()
    with patch(
        "apps.conversion.landing_pages.landing_page_engine.get_landing_page_engine",
        return_value=engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "generate_landing_headlines", {"product": "Yoga Mat Pro", "audience": "yogis"}
        )

    assert media == {}
    assert "Headline variants" in obs


async def test_landing_page_stats_empty_state():
    engine = LandingPageEngine()
    with patch(
        "apps.conversion.landing_pages.landing_page_engine.get_landing_page_engine",
        return_value=engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("landing_page_stats", {})

    assert media == {}
    assert "no landing pages" in obs.lower()


async def test_analyze_pricing_reachable_from_tool_dispatch():
    engine = PricingIntelligence()
    with patch(
        "apps.market.pricing.pricing_intelligence.get_pricing_intelligence", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "analyze_pricing",
            {
                "product_name": "Yoga Mat Pro",
                "category": "fitness",
                "our_price": 49.0,
                "competitors": [
                    {"competitor": "CompA", "price": 40.0},
                    {"competitor": "CompB", "price": 60.0},
                ],
            },
        )

    assert media == {}
    assert "Yoga Mat Pro" in obs
    assert "$40.00" in obs and "$60.00" in obs


async def test_analyze_pricing_requires_product_and_price():
    mind = AriaMind()
    obs, media = await mind._execute_tool("analyze_pricing", {"product_name": "Yoga Mat"})

    assert media == {}
    assert "price" in obs.lower()


async def test_suggest_dynamic_price_reachable_from_tool_dispatch():
    engine = PricingIntelligence()
    with patch(
        "apps.market.pricing.pricing_intelligence.get_pricing_intelligence", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "suggest_dynamic_price",
            {"product": "Yoga Mat Pro", "inventory_level": "low", "demand_signal": "high"},
        )

    assert media == {}
    assert "Suggested price" in obs


async def test_build_pricing_strategy_reachable_from_tool_dispatch():
    engine = PricingIntelligence()
    with patch(
        "apps.market.pricing.pricing_intelligence.get_pricing_intelligence", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "build_pricing_strategy",
            {"niche": "fitness", "product_type": "physical good", "target_margin_pct": 55},
        )

    assert media == {}
    assert "pricing strategy for fitness" in obs.lower()


async def test_pricing_dashboard_empty_state():
    engine = PricingIntelligence()
    with patch(
        "apps.market.pricing.pricing_intelligence.get_pricing_intelligence", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("pricing_dashboard", {})

    assert media == {}
    assert "no pricing analyses" in obs.lower()


async def test_pricing_dashboard_reachable_from_tool_dispatch():
    engine = PricingIntelligence()
    with patch(
        "apps.market.pricing.pricing_intelligence.get_pricing_intelligence", return_value=engine
    ):
        mind = AriaMind()
        await mind._execute_tool(
            "analyze_pricing",
            {
                "product_name": "Yoga Mat Pro",
                "category": "fitness",
                "our_price": 49.0,
                "competitors": [{"competitor": "CompA", "price": 45.0}],
            },
        )
        obs, media = await mind._execute_tool("pricing_dashboard", {})

    assert media == {}
    assert "Pricing dashboard" in obs
