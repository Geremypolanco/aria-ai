"""Regression coverage for the `add_goal` / `update_goal` tools inside
AriaMind._execute_tool() — apps/core/cognition/aria_mind.py:2085-2101.

These two tools had zero test coverage before the Tool Router extraction
(verified by grepping tests/ for the literal strings) despite being the
branches with the most `self` coupling (self._load_goals /
self._apply_goal_action / self._save_goals via self._cache_client()) —
exactly the ones most likely to break silently when that coupling is
threaded through an external `ctx` object during the mechanical dispatch
conversion. Written and passing against the current if/elif implementation
before any refactor, so it also protects the pre-refactor behavior as-is —
including the existing quirk asserted in
test_update_goal_out_of_range_index_is_a_noop_but_still_reports_success,
which is characterized here deliberately, not fixed (out of scope for the
Tool Router extraction).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind

pytestmark = pytest.mark.asyncio


def _fake_cache(initial_goals: list[dict] | None = None) -> MagicMock:
    cache = MagicMock()
    cache.get = AsyncMock(return_value=initial_goals if initial_goals is not None else [])
    cache.set = AsyncMock(return_value=True)
    return cache


async def test_add_goal_persists_a_new_goal_via_cache():
    cache = _fake_cache(initial_goals=[])

    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "add_goal", {"text": "Grow MRR to $10k", "priority": 2}, email="owner@example.com"
        )

    assert "added" in obs.lower()
    assert media == {}
    cache.set.assert_awaited_once()
    saved_key, saved_goals = cache.set.await_args.args[:2]
    assert saved_key == mind.K_GOALS
    assert len(saved_goals) == 1
    assert saved_goals[0]["text"] == "Grow MRR to $10k"
    assert saved_goals[0]["priority"] == 2
    assert saved_goals[0]["status"] == "active"


async def test_update_goal_persists_progress_and_status():
    existing = [
        {"text": "Grow MRR", "priority": 5, "status": "active", "progress": "", "created_at": ""}
    ]
    cache = _fake_cache(initial_goals=existing)

    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "update_goal",
            {"index": 0, "progress": "50%", "status": "active"},
            email="owner@example.com",
        )

    assert "updated" in obs.lower()
    assert media == {}
    cache.set.assert_awaited_once()
    _, saved_goals = cache.set.await_args.args[:2]
    assert saved_goals[0]["progress"] == "50%"


async def test_update_goal_out_of_range_index_is_a_noop_but_still_reports_success():
    """Characterizes existing behavior, not desired behavior: _apply_goal_action
    silently skips the update when the index is out of range (never calls
    _save_goals), but _execute_tool's `update_goal` branch always returns the
    "updated successfully" text regardless of whether anything was actually
    saved. Preserving this exactly (bug and all) is the point of a
    characterization test — fixing it is a separate, explicit change, not a
    side effect of the Tool Router extraction."""
    cache = _fake_cache(initial_goals=[{"text": "x", "priority": 5, "status": "active"}])

    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "update_goal", {"index": 99, "progress": "50%"}, email="owner@example.com"
        )

    assert "updated" in obs.lower()
    assert media == {}
    cache.set.assert_not_awaited()


async def test_add_goal_and_update_goal_are_not_owner_gated():
    """Unlike execute_code/post_to_social/github_write, goal tools are not
    in AriaMind._OWNER_ONLY_TOOLS — any authenticated user can manage their
    own goals. Guards against an accidental gate being added silently."""
    cache = _fake_cache(initial_goals=[])
    mind = AriaMind()
    assert "add_goal" not in mind._OWNER_ONLY_TOOLS
    assert "update_goal" not in mind._OWNER_ONLY_TOOLS

    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        obs, _ = await mind._execute_tool(
            "add_goal", {"text": "test"}, email="random-user@example.com"
        )
    assert "reserved for ARIA's owner" not in obs
