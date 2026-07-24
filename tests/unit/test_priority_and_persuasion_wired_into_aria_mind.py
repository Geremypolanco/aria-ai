"""Regression test: PriorityEngine (apps/strategy/prioritization/priority_engine.py)
and PersuasionEngine (apps/psychology/conversion/persuasion_engine.py) — two
complete, working systems with their own singleton getters — had zero live
callers, the same pattern as RDWing and BrandEngine before them.

PriorityEngine is now wired in as add_priority_action, top_priorities, and
allocate_resources — a persistent, scored strategic backlog, distinct from
analyze_decision (a one-off comparison between named options).

PersuasionEngine is now wired in as recommend_persuasion_tactics,
score_copy_persuasion, and optimize_cta.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engines directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.psychology.conversion.persuasion_engine import PersuasionEngine
from apps.strategy.prioritization.priority_engine import PriorityEngine

pytestmark = pytest.mark.asyncio


class _FakeCache:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value
        return True


@pytest.fixture
def priority_engine():
    return PriorityEngine()


@pytest.fixture(autouse=True)
def _patch_cache():
    fake = _FakeCache()
    with patch("apps.strategy.prioritization.priority_engine.get_cache", return_value=fake):
        yield fake


async def test_add_priority_action_reachable_from_tool_dispatch(priority_engine):
    with patch(
        "apps.strategy.prioritization.priority_engine.get_priority_engine",
        return_value=priority_engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "add_priority_action",
            {
                "title": "Launch referral program",
                "estimated_roi": 8.0,
                "effort_score": 3.0,
                "leverage_score": 0.8,
                "compounding": True,
            },
        )

    assert media == {}
    assert "Launch referral program" in obs
    actions = await priority_engine.rank_actions()
    assert len(actions) == 1
    assert actions[0].compounding is True


async def test_add_priority_action_requires_title(priority_engine):
    with patch(
        "apps.strategy.prioritization.priority_engine.get_priority_engine",
        return_value=priority_engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("add_priority_action", {})

    assert media == {}
    assert "title" in obs.lower()


async def test_top_priorities_ranks_by_score(priority_engine):
    with patch(
        "apps.strategy.prioritization.priority_engine.get_priority_engine",
        return_value=priority_engine,
    ):
        mind = AriaMind()
        await mind._execute_tool(
            "add_priority_action",
            {"title": "Low value", "estimated_roi": 1.0, "leverage_score": 0.1},
        )
        await mind._execute_tool(
            "add_priority_action",
            {"title": "High value", "estimated_roi": 10.0, "leverage_score": 0.9},
        )
        obs, media = await mind._execute_tool("top_priorities", {"limit": 5})

    assert media == {}
    # "High value" must be ranked before "Low value"
    assert obs.index("High value") < obs.index("Low value")


async def test_allocate_resources_reachable_from_tool_dispatch(priority_engine):
    with patch(
        "apps.strategy.prioritization.priority_engine.get_priority_engine",
        return_value=priority_engine,
    ):
        mind = AriaMind()
        await mind._execute_tool(
            "add_priority_action",
            {"title": "Only action", "estimated_roi": 5.0, "leverage_score": 0.5},
        )
        obs, media = await mind._execute_tool(
            "allocate_resources", {"total_hours": 20, "total_budget_usd": 1000}
        )

    assert media == {}
    assert "Only action" in obs


async def test_recommend_persuasion_tactics_reachable_from_tool_dispatch():
    engine = PersuasionEngine()
    with patch(
        "apps.psychology.conversion.persuasion_engine.get_persuasion_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "recommend_persuasion_tactics",
            {"context": "product landing page checkout", "target_emotion": "urgency"},
        )

    assert media == {}
    assert "Recommended persuasion tactics" in obs


async def test_recommend_persuasion_tactics_requires_context():
    engine = PersuasionEngine()
    with patch(
        "apps.psychology.conversion.persuasion_engine.get_persuasion_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("recommend_persuasion_tactics", {})

    assert media == {}
    assert "persuade" in obs.lower()


async def test_score_copy_persuasion_detects_scarcity():
    engine = PersuasionEngine()
    with patch(
        "apps.psychology.conversion.persuasion_engine.get_persuasion_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "score_copy_persuasion", {"copy": "Only 3 spots left, ending soon!"}
        )

    assert media == {}
    assert "scarcity" in obs.lower()


async def test_optimize_cta_falls_back_to_default_principle_on_invalid_input():
    engine = PersuasionEngine()
    with patch(
        "apps.psychology.conversion.persuasion_engine.get_persuasion_engine", return_value=engine
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "optimize_cta", {"cta": "Buy Now", "principle": "not-a-real-principle"}
        )

    assert media == {}
    assert "scarcity" in obs.lower()  # falls back to SCARCITY per aria_mind.py's except-branch
