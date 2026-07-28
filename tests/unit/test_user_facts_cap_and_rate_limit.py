"""Regression test: UserFactStore.remember() had no upper bound at all —
unlike episodic_memory.py (200-item cap) or semantic_memory.py (500-item
working-memory cap with LRU eviction), a user could accumulate facts
indefinitely, each one triggering an HF embedding call with no rate limit
of its own. That's a real cost/abuse vector this table didn't have before
(Supabase has no TTL, unlike the Redis-backed stores).

Two independent guards added, both fail OPEN on infra errors (this is an
abuse guard, not a correctness guarantee — a Redis/Supabase hiccup must
never block a legitimate save):

  1. A write rate limit (apps.core.memory.redis_client.AriaCache.
     check_rate_limit) — bounds how many new facts one user can write per
     hour.
  2. A hard cap (MAX_FACTS_PER_USER) enforced by deleting the oldest rows
     past the cap after each successful insert.

Also covers the AriaCache.check_rate_limit() fix itself: it used to read a
failed INCR (Redis down/rejected) as "limit exceeded" and silently block
every caller during an outage — the exact opposite of what an abuse guard
should do when its own backing store is unavailable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.memory.user_facts import MAX_FACTS_PER_USER, UserFactStore

pytestmark = pytest.mark.asyncio


def _configured_settings():
    return patch.multiple(
        "apps.core.memory.user_facts.settings",
        SUPABASE_URL="https://fake.supabase.co",
        SUPABASE_KEY="fake-service-role-key",
    )


# ── AriaCache.check_rate_limit() itself ──────────────────────────────────
async def test_check_rate_limit_fails_open_when_redis_incr_errors():
    from apps.core.memory.redis_client import AriaCache

    cache = AriaCache.__new__(AriaCache)
    cache._cmd = AsyncMock(return_value=None)  # simulates a failed INCR

    allowed = await cache.check_rate_limit("some-key", max_calls=5, window_seconds=3600)

    assert allowed is True


async def test_check_rate_limit_blocks_once_over_the_max():
    from apps.core.memory.redis_client import AriaCache

    cache = AriaCache.__new__(AriaCache)
    cache._cmd = AsyncMock(return_value=6)  # 6th call, max is 5

    allowed = await cache.check_rate_limit("some-key", max_calls=5, window_seconds=3600)

    assert allowed is False


async def test_check_rate_limit_allows_under_the_max():
    from apps.core.memory.redis_client import AriaCache

    cache = AriaCache.__new__(AriaCache)
    cache._cmd = AsyncMock(return_value=3)

    allowed = await cache.check_rate_limit("some-key", max_calls=5, window_seconds=3600)

    assert allowed is True


# ── UserFactStore.remember()'s write rate limit ──────────────────────────
async def test_remember_blocked_when_rate_limited():
    fake_cache = AsyncMock()
    fake_cache.check_rate_limit = AsyncMock(return_value=False)

    store = UserFactStore()
    with (
        _configured_settings(),
        patch("apps.core.memory.redis_client.get_cache", return_value=fake_cache),
    ):
        memory_id = await store.remember("user-a@example.com", "another fact")

    assert memory_id is None
    fake_cache.check_rate_limit.assert_awaited_once_with(
        "user_facts_write:user-a@example.com", 20, 3600
    )


async def test_remember_proceeds_when_cache_unavailable():
    """No Redis at all (get_cache() returns None) must not block a save —
    the rate limit is an abuse guard, not a hard dependency."""
    fake_db = MagicMock()
    fake_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "mem-1"}]
    )
    fake_db.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value = MagicMock(
        data=[]
    )

    store = UserFactStore()
    with (
        _configured_settings(),
        patch("apps.core.memory.redis_client.get_cache", return_value=None),
        patch("apps.core.memory.embeddings.embed_text", AsyncMock(return_value=None)),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
    ):
        memory_id = await store.remember("user-a@example.com", "a fact")

    assert memory_id == "mem-1"


# ── The hard cap ──────────────────────────────────────────────────────────
async def test_remember_enforces_the_cap_by_deleting_oldest_overflow_rows():
    fake_cache = AsyncMock()
    fake_cache.check_rate_limit = AsyncMock(return_value=True)

    fake_db = MagicMock()
    fake_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "new-mem"}]
    )
    # Two rows sit past the cap and should be deleted.
    overflow_rows = [{"id": "oldest-1"}, {"id": "oldest-2"}]
    fake_db.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value = MagicMock(
        data=overflow_rows
    )
    delete_execute = MagicMock()
    fake_db.table.return_value.delete.return_value.eq.return_value.execute = delete_execute

    store = UserFactStore()
    with (
        _configured_settings(),
        patch("apps.core.memory.redis_client.get_cache", return_value=fake_cache),
        patch("apps.core.memory.embeddings.embed_text", AsyncMock(return_value=None)),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
    ):
        memory_id = await store.remember("user-a@example.com", "a new fact")

    assert memory_id == "new-mem"
    # The write must succeed even though cap enforcement deletes 2 rows.
    assert delete_execute.call_count == 2
    fake_db.table.return_value.select.return_value.eq.return_value.order.return_value.range.assert_called_with(
        MAX_FACTS_PER_USER, MAX_FACTS_PER_USER + 200
    )


async def test_cap_enforcement_failure_does_not_undo_a_successful_write():
    fake_cache = AsyncMock()
    fake_cache.check_rate_limit = AsyncMock(return_value=True)

    fake_db = MagicMock()
    fake_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "new-mem"}]
    )
    # Cap-enforcement's select blows up — must not affect the returned id.
    fake_db.table.return_value.select.side_effect = RuntimeError("supabase hiccup")

    store = UserFactStore()
    with (
        _configured_settings(),
        patch("apps.core.memory.redis_client.get_cache", return_value=fake_cache),
        patch("apps.core.memory.embeddings.embed_text", AsyncMock(return_value=None)),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
    ):
        memory_id = await store.remember("user-a@example.com", "a new fact")

    assert memory_id == "new-mem"
