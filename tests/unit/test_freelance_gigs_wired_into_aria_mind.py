"""Regression test: FiverrOptimizer (apps/acquisition/fiverr/) and
UpworkBidder (apps/acquisition/upwork/) — complete implementations with
their own singleton getters — had zero live callers. Fifth batch from the
full-repo dead-code audit (Shopify Revenue Suite, lead discovery/LinkedIn
outreach, landing pages/pricing, now freelance gig tools).

Wired into aria_mind.py's tool dispatcher as: create_fiverr_gig,
optimize_fiverr_title, fiverr_gig_analytics, evaluate_upwork_job,
write_upwork_proposal, optimize_upwork_profile, upwork_bidding_analytics.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engines directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.acquisition.fiverr.fiverr_optimizer import FiverrOptimizer
from apps.acquisition.upwork.upwork_bidder import UpworkBidder
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
    with (
        patch("apps.acquisition.fiverr.fiverr_optimizer.get_cache", return_value=_FakeCache()),
        patch("apps.acquisition.upwork.upwork_bidder.get_cache", return_value=_FakeCache()),
    ):
        yield


async def test_create_fiverr_gig_reachable_from_tool_dispatch():
    engine = FiverrOptimizer()
    with patch(
        "apps.acquisition.fiverr.fiverr_optimizer.get_fiverr_optimizer", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_fiverr_gig", {"service_type": "logo design", "niche": "startups"}
        )

    assert media == {}
    assert "SEO score" in obs
    assert "baseline templates" in obs


async def test_create_fiverr_gig_requires_service_and_niche():
    mind = AriaMind()
    obs, media = await mind._execute_tool("create_fiverr_gig", {})

    assert media == {}
    assert "niche" in obs.lower()


async def test_optimize_fiverr_title_reachable_from_tool_dispatch():
    engine = FiverrOptimizer()
    with patch(
        "apps.acquisition.fiverr.fiverr_optimizer.get_fiverr_optimizer", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "optimize_fiverr_title",
            {"current_title": "I will design a logo", "keyword": "minimalist logo design"},
        )

    assert media == {}
    assert "Optimized title" in obs


async def test_fiverr_gig_analytics_empty_state():
    engine = FiverrOptimizer()
    with patch(
        "apps.acquisition.fiverr.fiverr_optimizer.get_fiverr_optimizer", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("fiverr_gig_analytics", {})

    assert media == {}
    assert "no fiverr gigs" in obs.lower()


async def test_evaluate_upwork_job_reachable_from_tool_dispatch():
    engine = UpworkBidder()
    with patch("apps.acquisition.upwork.upwork_bidder.get_upwork_bidder", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "evaluate_upwork_job",
            {
                "title": "Build a Shopify store",
                "description": "Need a full Shopify build",
                "budget_min": 500,
                "budget_max": 1500,
                "skills_required": ["shopify", "liquid"],
                "our_skills": ["shopify", "liquid", "seo"],
            },
        )

    assert media == {}
    assert "Build a Shopify store" in obs
    assert "Fit score" in obs


async def test_evaluate_upwork_job_requires_title():
    mind = AriaMind()
    obs, media = await mind._execute_tool("evaluate_upwork_job", {})

    assert media == {}
    assert "title" in obs.lower()


async def test_write_upwork_proposal_reachable_from_tool_dispatch():
    engine = UpworkBidder()
    with patch("apps.acquisition.upwork.upwork_bidder.get_upwork_bidder", return_value=engine):
        mind = AriaMind()
        job = await engine.evaluate_job(
            "Build a Shopify store", "desc", 500, 1500, ["shopify"], ["shopify"]
        )
        obs, media = await mind._execute_tool(
            "write_upwork_proposal",
            {"job_id": job.job_id, "our_expertise": "Shopify development"},
        )

    assert media == {}
    assert "Proposal" in obs


async def test_optimize_upwork_profile_reachable_from_tool_dispatch():
    engine = UpworkBidder()
    with patch("apps.acquisition.upwork.upwork_bidder.get_upwork_bidder", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "optimize_upwork_profile",
            {"skills": ["shopify", "liquid"], "specialization": "Shopify development"},
        )

    assert media == {}
    assert "Headline" in obs
    assert "Portfolio ideas" in obs


async def test_upwork_bidding_analytics_empty_state():
    engine = UpworkBidder()
    with patch("apps.acquisition.upwork.upwork_bidder.get_upwork_bidder", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool("upwork_bidding_analytics", {})

    assert media == {}
    assert "no upwork jobs" in obs.lower()
