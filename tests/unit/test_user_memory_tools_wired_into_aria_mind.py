"""Regression test: the three new per-user long-term memory tools
(remember_user_fact, list_user_facts, forget_user_fact — built on
apps/core/memory/user_facts.py's UserFactStore) as reached through
AriaMind._execute_tool, exactly as a live conversation would.

Unlike the Shopify/finance tools (which are owner-only because they write
to ONE global Redis key shared by every user — see AriaMind._OWNER_ONLY_TOOLS),
these three are open to every signed-in user, because UserFactStore is
correctly scoped per-user at the storage layer: each user manages only their
own facts, and every dispatch case below is hard-scoped to the `email`
AriaMind itself resolved from the verified session (never a value taken from
tool args), so there is no argument a user could pass to reach someone
else's data.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind

pytestmark = pytest.mark.asyncio


async def test_remember_user_fact_requires_signed_in_email():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "remember_user_fact", {"content": "prefers concise answers"}, email=""
    )
    assert media == {}
    assert "signed in" in obs.lower()


async def test_remember_user_fact_requires_content():
    mind = AriaMind()
    obs, media = await mind._execute_tool("remember_user_fact", {}, email="user-a@example.com")
    assert media == {}
    assert "remember" in obs.lower()


async def test_remember_user_fact_scopes_to_the_callers_own_email_only():
    """The dispatch case has no code path that reads a user/email/target
    argument out of `args` — it always calls remember() with the `email`
    AriaMind itself resolved, so a malicious tool_args payload trying to
    smuggle a different target user is simply ignored."""
    fake_store = AsyncMock()
    fake_store.remember = AsyncMock(return_value="mem-1")

    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "remember_user_fact",
            {
                "content": "prefers concise answers",
                "category": "preference",
                # An attempted cross-user target — must be ignored entirely.
                "user_id": "someone-else@example.com",
                "email": "someone-else@example.com",
            },
            email="user-a@example.com",
        )

    assert media == {}
    assert "remember" in obs.lower()
    fake_store.remember.assert_awaited_once_with(
        "user-a@example.com",
        "prefers concise answers",
        category="preference",
        importance=0.5,
    )


async def test_remember_user_fact_rejects_invalid_category():
    fake_store = AsyncMock()
    fake_store.remember = AsyncMock(return_value="mem-1")

    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        mind = AriaMind()
        await mind._execute_tool(
            "remember_user_fact",
            {"content": "x", "category": "not_a_real_category"},
            email="user-a@example.com",
        )

    _, kwargs = fake_store.remember.call_args
    assert kwargs["category"] == "fact"  # falls back to the safe default


async def test_remember_user_fact_reports_when_storage_unavailable():
    fake_store = AsyncMock()
    fake_store.remember = AsyncMock(return_value=None)  # Supabase not configured

    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "remember_user_fact", {"content": "x"}, email="user-a@example.com"
        )

    assert media == {}
    assert "couldn't save" in obs.lower()


async def test_list_user_facts_requires_signed_in_email():
    mind = AriaMind()
    obs, media = await mind._execute_tool("list_user_facts", {}, email="")
    assert media == {}
    assert "signed in" in obs.lower()


async def test_list_user_facts_scopes_to_the_callers_own_email_only():
    fake_store = AsyncMock()
    fake_store.list_all = AsyncMock(
        return_value=[
            {"id": "mem-1", "content": "prefers concise answers", "category": "preference"}
        ]
    )

    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "list_user_facts", {"user_id": "someone-else@example.com"}, email="user-a@example.com"
        )

    assert media == {}
    assert "prefers concise answers" in obs
    fake_store.list_all.assert_awaited_once_with("user-a@example.com", limit=50)


async def test_list_user_facts_empty_state():
    fake_store = AsyncMock()
    fake_store.list_all = AsyncMock(return_value=[])

    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        mind = AriaMind()
        obs, media = await mind._execute_tool("list_user_facts", {}, email="user-a@example.com")

    assert media == {}
    assert "don't have anything" in obs.lower()


async def test_forget_user_fact_requires_signed_in_email():
    mind = AriaMind()
    obs, media = await mind._execute_tool("forget_user_fact", {"memory_id": "mem-1"}, email="")
    assert media == {}
    assert "signed in" in obs.lower()


async def test_forget_user_fact_requires_memory_id():
    mind = AriaMind()
    obs, media = await mind._execute_tool("forget_user_fact", {}, email="user-a@example.com")
    assert media == {}
    assert "memory_id" in obs.lower() or "which memory" in obs.lower()


async def test_forget_user_fact_scopes_to_the_callers_own_email_only():
    fake_store = AsyncMock()
    fake_store.forget = AsyncMock(return_value=True)

    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "forget_user_fact", {"memory_id": "mem-1"}, email="user-a@example.com"
        )

    assert media == {}
    assert "forgotten" in obs.lower()
    fake_store.forget.assert_awaited_once_with("user-a@example.com", "mem-1")


async def test_forget_user_fact_reports_failure_when_not_owned_or_missing():
    fake_store = AsyncMock()
    fake_store.forget = AsyncMock(return_value=False)

    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "forget_user_fact", {"memory_id": "not-mine"}, email="user-a@example.com"
        )

    assert media == {}
    assert "couldn't find" in obs.lower()


async def test_none_of_the_three_tools_are_owner_gated():
    """These are correctly per-user-scoped at the storage layer (unlike the
    Shopify/finance tools) — they must stay open to every signed-in user,
    not get accidentally added to _OWNER_ONLY_TOOLS."""
    for tool in ("remember_user_fact", "list_user_facts", "forget_user_fact"):
        assert tool not in AriaMind._OWNER_ONLY_TOOLS
