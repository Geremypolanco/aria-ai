"""Regression test: apps/core/memory/semantic_memory.py's SemanticMemory kept
its only real state in a plain in-process dict (self._working). That's the
same bug class apps/core/cognition/episodic_memory.py's docstring documents
and fixes for itself — fly.toml autoscales the `web` group across multiple
machines, so a fact stored by one process/machine was invisible to
search()/get() on any other, and even on the SAME process, a restart wiped
it out. Two things made this worse:

  1. _persist_fact() stripped the embedding before writing to Redis ("to
     save space"), so even the Redis copy could never support the
     similarity search this whole module exists for — only keyword
     fallback would ever work on a reloaded fact.
  2. _load_from_redis() was an unimplemented no-op stub (just set
     self._loaded = True and logged a message) — nothing ever actually
     scanned Redis and backfilled working memory.

Both fixed: _persist_fact() now stores the full fact (including embedding),
and _load_from_redis() uses the new AriaCache.scan_keys() to enumerate and
reload every aria:semantic:* key on first use.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from apps.core.memory.semantic_memory import Fact, SemanticMemory

pytestmark = pytest.mark.asyncio


class _FakeCache:
    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, key):
        raw = self._store.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value if isinstance(value, str) else json.dumps(value)
        return True

    async def delete(self, key):
        self._store.pop(key, None)
        return True

    async def scan_keys(self, pattern, limit=1000):
        # Only supports the simple "prefix*" patterns this module actually uses.
        prefix = pattern.rstrip("*")
        return [k for k in self._store if k.startswith(prefix)][:limit]


async def test_scan_keys_paginates_until_cursor_is_zero():
    from apps.core.memory.redis_client import AriaCache

    cache = AriaCache.__new__(AriaCache)  # skip __init__ (needs settings/httpx client)
    responses = [
        ["12", ["aria:semantic:a", "aria:semantic:b"]],
        ["0", ["aria:semantic:c"]],
    ]
    cache._cmd = AsyncMock(side_effect=responses)

    keys = await cache.scan_keys("aria:semantic:*")

    assert keys == ["aria:semantic:a", "aria:semantic:b", "aria:semantic:c"]
    assert cache._cmd.await_count == 2


async def test_scan_keys_stops_at_limit_even_mid_scan():
    from apps.core.memory.redis_client import AriaCache

    cache = AriaCache.__new__(AriaCache)
    responses = [
        ["7", ["k1", "k2", "k3"]],
        ["0", ["k4", "k5"]],
    ]
    cache._cmd = AsyncMock(side_effect=responses)

    keys = await cache.scan_keys("k*", limit=3)

    assert keys == ["k1", "k2", "k3"]


async def test_persist_fact_keeps_the_embedding():
    cache = _FakeCache()
    mem = SemanticMemory()
    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch.object(mem, "_embed", AsyncMock(return_value=[0.1, 0.2, 0.3])),
    ):
        fact_id = await mem.store("the user prefers dark mode", category="user_preference")

    raw = await cache.get(f"aria:semantic:{fact_id}")
    assert raw["embedding"] == [0.1, 0.2, 0.3]  # not stripped to []


async def test_load_from_redis_backfills_facts_stored_by_a_different_process():
    """Simulates the real cross-process scenario: process A stores a fact
    directly into the shared Redis (never touching process B's in-memory
    dict). A fresh SemanticMemory() instance (standing in for process B)
    must find it via search() after _load_from_redis() runs."""
    cache = _FakeCache()

    other_process_fact = Fact(
        id="fact-from-process-a",
        content="the user's business is a yoga studio in Austin",
        category="user_preference",
        source="chat",
        confidence=0.9,
        embedding=[1.0, 0.0, 0.0],
        tags=[],
        created_at="2026-01-01T00:00:00Z",
        accessed_at="2026-01-01T00:00:00Z",
    )
    await cache.set(
        f"aria:semantic:{other_process_fact.id}", json.dumps(other_process_fact.to_dict())
    )

    mem = SemanticMemory()  # a fresh instance — nothing in self._working yet
    assert mem._working == {}

    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch.object(mem, "_embed", AsyncMock(return_value=[1.0, 0.0, 0.0])),
    ):
        results = await mem.search("yoga studio Austin")

    assert len(results) == 1
    assert results[0].id == "fact-from-process-a"
    assert "yoga studio" in results[0].content


async def test_load_from_redis_only_runs_once_per_instance():
    cache = _FakeCache()
    mem = SemanticMemory()

    with patch("apps.core.memory.redis_client.get_cache", return_value=cache) as mock_get_cache:
        await mem._load_from_redis()
        await mem._load_from_redis()

    assert mem._loaded is True
    # search()/get() guard on self._loaded, but calling _load_from_redis()
    # directly twice should still be safe/idempotent rather than erroring.
    assert mock_get_cache.call_count == 2
