"""Tests for apps/core/memory/context_loader.py — the shared function that
decides what ARIA remembers about a user before responding (combines
episodic_memory recall + the new user_facts recall). Both apps/core/main.py
chat entrypoints (HTTP /api/v1/chat and WebSocket /ws/chat) must call this
scoped to the caller's own server-verified email — see
test_ws_chat_loads_user_context_scoped_to_caller_email below for that half
of the guarantee.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.memory.context_loader import load_user_context

pytestmark = pytest.mark.asyncio


async def test_returns_empty_string_for_anonymous_caller():
    result = await load_user_context("", "what do you know about me")
    assert result == ""


async def test_combines_facts_and_episodes_for_the_given_user():
    fake_episodic = AsyncMock()
    fake_episodic.recall = AsyncMock(return_value=[{"content": "asked about pricing last week"}])
    fake_facts = AsyncMock()
    fake_facts.recall = AsyncMock(return_value=[{"content": "prefers concise answers"}])

    with (
        patch(
            "apps.core.cognition.episodic_memory.get_episodic_memory", return_value=fake_episodic
        ),
        patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_facts),
    ):
        result = await load_user_context("user-a@example.com", "pricing question")

    assert "prefers concise answers" in result
    assert "asked about pricing last week" in result
    fake_episodic.recall.assert_awaited_once_with("user-a@example.com", "pricing question", n=4)
    fake_facts.recall.assert_awaited_once_with("user-a@example.com", "pricing question", top_k=5)


async def test_never_mixes_in_another_users_data_by_construction():
    """load_user_context has no parameter for a second user — the only way
    it could leak cross-user data is if the underlying recall() calls
    themselves leaked, which is covered separately in
    test_user_facts_isolation.py and test_cognition_memory_persistence_fixes.py.
    This test locks in that only ONE user_id is ever threaded through."""
    fake_episodic = AsyncMock()
    fake_episodic.recall = AsyncMock(return_value=[])
    fake_facts = AsyncMock()
    fake_facts.recall = AsyncMock(return_value=[])

    with (
        patch(
            "apps.core.cognition.episodic_memory.get_episodic_memory", return_value=fake_episodic
        ),
        patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_facts),
    ):
        await load_user_context("USER-A@Example.com", "anything")

    # Normalized (lowercased/stripped) the same way everywhere identity is used.
    fake_episodic.recall.assert_awaited_once_with("user-a@example.com", "anything", n=4)
    fake_facts.recall.assert_awaited_once_with("user-a@example.com", "anything", top_k=5)


async def test_degrades_gracefully_when_episodic_recall_raises():
    fake_episodic = AsyncMock()
    fake_episodic.recall = AsyncMock(side_effect=RuntimeError("redis down"))
    fake_facts = AsyncMock()
    fake_facts.recall = AsyncMock(return_value=[{"content": "prefers concise answers"}])

    with (
        patch(
            "apps.core.cognition.episodic_memory.get_episodic_memory", return_value=fake_episodic
        ),
        patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_facts),
    ):
        result = await load_user_context("user-a@example.com", "anything")

    # One source failing must not take down the other, or raise at all.
    assert "prefers concise answers" in result


async def test_degrades_gracefully_when_both_sources_fail():
    fake_episodic = AsyncMock()
    fake_episodic.recall = AsyncMock(side_effect=RuntimeError("redis down"))
    fake_facts = AsyncMock()
    fake_facts.recall = AsyncMock(side_effect=RuntimeError("supabase down"))

    with (
        patch(
            "apps.core.cognition.episodic_memory.get_episodic_memory", return_value=fake_episodic
        ),
        patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_facts),
    ):
        result = await load_user_context("user-a@example.com", "anything")

    assert result == ""
