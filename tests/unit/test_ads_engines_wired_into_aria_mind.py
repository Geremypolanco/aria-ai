"""Regression test: AudienceSegmenter (apps/ads/audiences/) and
RetargetingEngine (apps/ads/retargeting/) — two complete implementations
with their own singleton getters already in place — had zero live callers,
same pattern as the other audited-but-disconnected modules wired in earlier
this session.

Wired into aria_mind.py's tool dispatcher as: create_ad_audience,
estimate_ad_cac, suggest_ad_targeting, create_retargeting_campaign,
cart_abandonment_sequence, record_retargeting_metrics,
retargeting_performance.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engines directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.ads.audiences.audience_segmenter import AudienceSegmenter
from apps.ads.retargeting.retargeting_engine import RetargetingEngine
from apps.core.cognition.aria_mind import AriaMind

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
    fake_segmenter = _FakeCache()
    fake_retargeting = _FakeCache()
    with (
        patch(
            "apps.ads.audiences.audience_segmenter.get_cache",
            return_value=fake_segmenter,
        ),
        patch(
            "apps.ads.retargeting.retargeting_engine.get_cache",
            return_value=fake_retargeting,
        ),
    ):
        yield


async def test_create_ad_audience_reachable_from_tool_dispatch():
    segmenter = AudienceSegmenter()
    with patch(
        "apps.ads.audiences.audience_segmenter.get_audience_segmenter",
        return_value=segmenter,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_ad_audience",
            {"name": "Fitness buyers", "criteria": {"age_range": "25-34"}, "platforms": ["meta"]},
        )

    assert media == {}
    assert "Fitness buyers" in obs
    assert "Estimated CPM" in obs


async def test_create_ad_audience_requires_name():
    segmenter = AudienceSegmenter()
    with patch(
        "apps.ads.audiences.audience_segmenter.get_audience_segmenter",
        return_value=segmenter,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("create_ad_audience", {})

    assert media == {}
    assert "name" in obs.lower()


async def test_estimate_ad_cac_reachable_from_tool_dispatch():
    segmenter = AudienceSegmenter()
    with patch(
        "apps.ads.audiences.audience_segmenter.get_audience_segmenter",
        return_value=segmenter,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "estimate_ad_cac",
            {"estimated_cpm": 10.0, "product_price": 49.0, "expected_cvr": 0.02},
        )

    assert media == {}
    assert "CAC estimate" in obs


async def test_suggest_ad_targeting_reachable_from_tool_dispatch():
    segmenter = AudienceSegmenter()
    with patch(
        "apps.ads.audiences.audience_segmenter.get_audience_segmenter",
        return_value=segmenter,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "suggest_ad_targeting", {"product": "resistance bands", "niche": "home fitness"}
        )

    assert media == {}
    assert "Interest targeting" in obs
    assert "Exclusion audiences" in obs


async def test_create_retargeting_campaign_reachable_from_tool_dispatch():
    engine = RetargetingEngine()
    with patch(
        "apps.ads.retargeting.retargeting_engine.get_retargeting_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_retargeting_campaign",
            {
                "product_name": "Resistance Bands",
                "audience_type": "cart_abandoners",
                "user_ids": ["u1", "u2"],
                "budget_daily_usd": 25,
                "platform": "meta",
            },
        )

    assert media == {}
    assert "Retargeting campaign" in obs
    assert "Resistance Bands" in obs


async def test_cart_abandonment_sequence_reachable_from_tool_dispatch():
    engine = RetargetingEngine()
    with patch(
        "apps.ads.retargeting.retargeting_engine.get_retargeting_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "cart_abandonment_sequence",
            {"cart_items": [{"name": "Resistance Bands"}], "user_id": "u1"},
        )

    assert media == {}
    assert "Cart abandonment sequence" in obs
    assert "u1" in obs


async def test_record_retargeting_metrics_updates_existing_campaign():
    engine = RetargetingEngine()
    with patch(
        "apps.ads.retargeting.retargeting_engine.get_retargeting_engine", return_value=engine
    ):
        mind = AriaMind()
        _, _ = await mind._execute_tool(
            "create_retargeting_campaign",
            {"product_name": "Resistance Bands", "audience_type": "product_viewers"},
        )
        campaign_id = engine._campaigns[0]["campaign_id"]
        obs, media = await mind._execute_tool(
            "record_retargeting_metrics",
            {"campaign_id": campaign_id, "impressions": 1000, "clicks": 50, "spend": 20.0},
        )

    assert media == {}
    assert "recorded" in obs.lower()


async def test_record_retargeting_metrics_unknown_campaign():
    engine = RetargetingEngine()
    with patch(
        "apps.ads.retargeting.retargeting_engine.get_retargeting_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "record_retargeting_metrics", {"campaign_id": "does-not-exist"}
        )

    assert media == {}
    assert "no retargeting campaign" in obs.lower()


async def test_retargeting_performance_reachable_from_tool_dispatch():
    engine = RetargetingEngine()
    with patch(
        "apps.ads.retargeting.retargeting_engine.get_retargeting_engine", return_value=engine
    ):
        mind = AriaMind()
        await mind._execute_tool(
            "create_retargeting_campaign",
            {"product_name": "Resistance Bands", "audience_type": "product_viewers"},
        )
        obs, media = await mind._execute_tool("retargeting_performance", {})

    assert media == {}
    assert "Retargeting performance" in obs
    assert "Top performers" in obs


async def test_retargeting_performance_empty_state():
    engine = RetargetingEngine()
    with patch(
        "apps.ads.retargeting.retargeting_engine.get_retargeting_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("retargeting_performance", {})

    assert media == {}
    assert "no retargeting campaigns" in obs.lower()
