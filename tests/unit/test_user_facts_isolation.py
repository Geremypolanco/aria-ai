"""Regression/isolation tests for apps/core/memory/user_facts.py — the new
durable, per-user semantic memory store (Supabase + pgvector) built for
multi-user persistent memory.

The core guarantee under test: nothing in UserFactStore can read or affect
more than one user's rows, regardless of what a caller passes in — every
query is scoped by user_id, including the vector-similarity RPC and the
delete path (a guessed/leaked memory_id must never delete another user's
fact).

Exercises UserFactStore directly (unit-level), the way
test_cognition_memory_persistence_fixes.py exercises EpisodicMemory/
WorldState — with a MagicMock Supabase client (create_client() returns a
SYNCHRONOUS client; .execute() is a plain call, not a coroutine).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.memory.user_facts import UserFactStore

pytestmark = pytest.mark.asyncio


def _configured_settings():
    return patch.multiple(
        "apps.core.memory.user_facts.settings",
        SUPABASE_URL="https://fake.supabase.co",
        SUPABASE_KEY="fake-service-role-key",
    )


async def test_remember_requires_user_id():
    store = UserFactStore()
    with _configured_settings():
        result = await store.remember("", "likes dark mode")
    assert result is None


async def test_remember_requires_content():
    store = UserFactStore()
    with _configured_settings():
        result = await store.remember("user-a@example.com", "")
    assert result is None


async def test_remember_returns_none_when_supabase_not_configured():
    store = UserFactStore()
    with patch.multiple("apps.core.memory.user_facts.settings", SUPABASE_URL="", SUPABASE_KEY=""):
        result = await store.remember("user-a@example.com", "likes dark mode")
    assert result is None


async def test_remember_inserts_row_scoped_to_user_id():
    fake_db = MagicMock()
    fake_table = MagicMock()
    fake_table.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "mem-1", "user_id": "user-a@example.com"}]
    )
    fake_db.table.return_value = fake_table

    store = UserFactStore()
    with (
        _configured_settings(),
        patch("apps.core.memory.embeddings.embed_text", AsyncMock(return_value=None)),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
    ):
        memory_id = await store.remember(
            "USER-A@example.com  ", "prefers concise answers", category="preference"
        )

    assert memory_id == "mem-1"
    fake_db.table.assert_called_with("aria_user_memories")
    inserted = fake_table.insert.call_args[0][0]
    # Email is normalized (stripped/lowercased) before it's ever used as a key.
    assert inserted["user_id"] == "user-a@example.com"
    assert inserted["content"] == "prefers concise answers"
    assert inserted["category"] == "preference"


async def test_recall_requires_user_id():
    store = UserFactStore()
    with _configured_settings():
        result = await store.recall("", "what does this user like")
    assert result == []


async def test_recall_vector_path_always_passes_the_exact_caller_user_id():
    """The RPC call is the real isolation boundary for vector search — this
    asserts the function is never invoked with anything other than the
    caller's own user_id, so a bug elsewhere (e.g. accidentally reusing a
    stale user_id) would fail this test rather than silently leak."""
    fake_db = MagicMock()
    fake_db.rpc.return_value.execute.return_value = MagicMock(
        data=[{"id": "mem-1", "content": "prefers concise answers"}]
    )

    store = UserFactStore()
    with (
        _configured_settings(),
        patch("apps.core.memory.embeddings.embed_text", AsyncMock(return_value=[0.1, 0.2, 0.3])),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
    ):
        results = await store.recall("user-a@example.com", "what do they like", top_k=3)

    assert results == [{"id": "mem-1", "content": "prefers concise answers"}]
    fake_db.rpc.assert_called_once()
    rpc_name, rpc_args = fake_db.rpc.call_args[0]
    assert rpc_name == "match_user_memories"
    assert rpc_args["p_user_id"] == "user-a@example.com"
    assert rpc_args["p_match_count"] == 3


async def test_recall_never_returns_another_users_memories_via_keyword_fallback():
    """No embeddings available (HF not configured) — falls back to
    Python-side keyword search. Even in this fallback, the underlying
    Supabase query for the candidate rows filters by user_id (list_all),
    so user B's facts are never even fetched into the candidate pool for
    user A's recall."""
    fake_db = MagicMock()

    def fake_table(name):
        t = MagicMock()

        def eq_side_effect(*args, **kwargs):
            # Emulate a real per-user-scoped table: only ever return rows
            # matching whatever user_id was actually filtered on.
            called_user = eq_side_effect.calls.get("user_id")
            if args and args[0] == "user_id":
                eq_side_effect.calls["user_id"] = args[1]
                called_user = args[1]
            filtered = MagicMock()
            filtered.order.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[r for r in _ALL_ROWS if r["user_id"] == called_user]
            )
            filtered.eq = eq_side_effect
            return filtered

        eq_side_effect.calls = {}
        t.select.return_value.eq = eq_side_effect
        return t

    _ALL_ROWS = [
        {"user_id": "user-a@example.com", "content": "prefers dark themes and concise replies"},
        {"user_id": "user-b@example.com", "content": "prefers detailed step by step explanations"},
    ]
    fake_db.table.side_effect = fake_table
    # No embedding => vector path skipped entirely, going straight to fallback.
    fake_db.rpc = MagicMock()

    store = UserFactStore()
    with (
        _configured_settings(),
        patch("apps.core.memory.embeddings.embed_text", AsyncMock(return_value=None)),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
    ):
        a_results = await store.recall("user-a@example.com", "concise replies preference")
        b_results = await store.recall("user-b@example.com", "concise replies preference")

    fake_db.rpc.assert_not_called()  # no embedding => vector RPC never attempted
    assert len(a_results) == 1 and "concise" in a_results[0]["content"]
    assert b_results == []  # "concise" doesn't keyword-match user B's fact


async def test_list_all_scopes_query_to_user_id():
    fake_db = MagicMock()
    fake_query = fake_db.table.return_value.select.return_value.eq.return_value
    fake_query.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"id": "mem-1", "user_id": "user-a@example.com"}]
    )

    store = UserFactStore()
    with (
        _configured_settings(),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
    ):
        results = await store.list_all("user-a@example.com")

    assert len(results) == 1
    fake_db.table.return_value.select.return_value.eq.assert_called_with(
        "user_id", "user-a@example.com"
    )


async def test_list_all_runs_the_blocking_supabase_call_off_the_event_loop():
    """Regression: q.execute() is synchronous (supabase-py), so calling it
    directly inside this async method would block the whole event loop for
    the duration of the HTTP round-trip — a real problem now that
    Mission Control's memory inspector calls list_all() inside an
    asyncio.gather() alongside other concurrent work."""
    fake_db = MagicMock()
    fake_query = fake_db.table.return_value.select.return_value.eq.return_value
    fake_query.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"id": "mem-1", "user_id": "user-a@example.com"}]
    )

    store = UserFactStore()
    with (
        _configured_settings(),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
        patch("asyncio.to_thread", wraps=asyncio.to_thread) as fake_to_thread,
    ):
        results = await store.list_all("user-a@example.com")

    assert len(results) == 1
    fake_to_thread.assert_awaited_once()
    assert (
        fake_to_thread.call_args[0][0] == fake_query.order.return_value.limit.return_value.execute
    )


async def test_forget_requires_user_id_and_memory_id():
    store = UserFactStore()
    with _configured_settings():
        assert await store.forget("", "mem-1") is False
        assert await store.forget("user-a@example.com", "") is False


async def test_forget_only_deletes_when_both_id_and_user_id_match():
    """The critical BOLA-style guard: even if user B somehow learns user A's
    memory_id (e.g. by guessing a UUID), calling forget() as user B must not
    delete it — the delete query filters on user_id too, so it matches zero
    rows for the wrong caller."""
    fake_db = MagicMock()
    fake_delete_chain = fake_db.table.return_value.delete.return_value.eq.return_value.eq
    # Correct owner (user-a) deletes successfully...
    fake_delete_chain.return_value.execute.return_value = MagicMock(data=[{"id": "mem-1"}])

    store = UserFactStore()
    with (
        _configured_settings(),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
    ):
        ok = await store.forget("user-a@example.com", "mem-1")

    assert ok is True
    # Verify BOTH filters were applied — id AND user_id, in that order.
    first_eq = fake_db.table.return_value.delete.return_value.eq
    first_eq.assert_called_with("id", "mem-1")
    fake_delete_chain.assert_called_with("user_id", "user-a@example.com")


async def test_forget_returns_false_when_wrong_owner_matches_no_rows():
    fake_db = MagicMock()
    fake_delete_chain = fake_db.table.return_value.delete.return_value.eq.return_value.eq
    # Wrong owner: Supabase's own WHERE id=... AND user_id=... matches nothing.
    fake_delete_chain.return_value.execute.return_value = MagicMock(data=[])

    store = UserFactStore()
    with (
        _configured_settings(),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
    ):
        ok = await store.forget("user-b@example.com", "mem-belongs-to-user-a")

    assert ok is False
