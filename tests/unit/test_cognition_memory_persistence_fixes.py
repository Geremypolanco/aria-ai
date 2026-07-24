"""Regression tests for a cluster of persistence bugs across apps/core/cognition/
and apps/core/memory/ that all silently broke ARIA's actual memory/reasoning
persistence, caught only by broad `except Exception` blocks:

1. Double-JSON-decode: AriaCache.get() already deserializes JSON (see
   redis_client.py), but several callers ran json.loads() on the result again,
   raising TypeError every time (a dict/list isn't str/bytes/bytearray) and
   silently returning None/empty — so nothing persisted could ever be loaded
   back. Affected: planner.load_plan, reasoning_engine.load_from_redis,
   reflection_engine.load_decisions, world_state.load,
   semantic_memory._load_fact_from_redis, continuous_learning's topic
   frequency counter.
2. ttl_seconds misplaced onto json.dumps() instead of cache.set() — json.dumps
   doesn't accept that kwarg, so the call always raised TypeError and the
   value was never written to Redis at all. Affected: reflection_engine
   ._persist_decisions, world_state.persist.
3. cache.set(key, value, ttl_seconds=...) called with the wrong kwarg name
   (`ttl=`) — AriaCache.set has no **kwargs, so this raised TypeError on every
   call. Affected: model_router.py (3 sites), continuous_learning.py (4 sites).
4. episodic_memory._persist_episode had value and ttl_seconds transposed
   (`cache.set(key, 86400*7, json.dumps(...))`) — the episode content was
   never actually stored (the cached "value" was the literal string
   "604800"), and the malformed ttl_seconds argument broke Redis's EX arg.
5. AriaDatabase (supabase_client.py) had no .table() passthrough, so
   world_state.persist / episodic_memory._persist_episode's
   `db.table(...).upsert/insert(...)` calls raised AttributeError on every
   invocation — Supabase persistence for both subsystems silently never
   happened despite explicit "persists in Supabase" docstring claims.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


class FakeCache:
    """Mimics AriaCache's real contract: set() serializes non-str values to
    JSON, get() deserializes JSON back — exactly like redis_client.AriaCache,
    so these tests exercise the real round-trip bug, not just a mock stub."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value if isinstance(value, str) else json.dumps(value)
        return True

    async def get(self, key):
        raw = self._store.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def rpush(self, *a, **kw):
        return True

    async def lpush(self, *a, **kw):
        return True

    async def ltrim(self, *a, **kw):
        return True


async def test_planner_save_and_load_plan_round_trips():
    from apps.core.cognition.planner import ARIAPlanner, Plan, PlanStatus

    plan = Plan(id="p1", goal="ship feature", context={}, tasks=[])
    plan.status = PlanStatus.ACTIVE

    cache = FakeCache()
    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        planner = ARIAPlanner()
        await planner._persist_plan(plan)
        loaded = await planner.load_plan("p1")

    assert loaded is not None
    assert loaded.id == "p1"
    assert loaded.goal == "ship feature"


async def test_reasoning_engine_persist_and_load_round_trips():
    from apps.core.cognition.reasoning_engine import ReasoningEngine, ReasoningResult

    result = ReasoningResult(
        id="r1",
        question="why?",
        context={},
        steps=[],
        critiques=[],
        conclusion="because",
        confidence=0.9,
        uncertainty_flags=[],
        action_recommendation="proceed",
        reasoning_time_ms=42,
        created_at="2026-01-01T00:00:00Z",
    )

    cache = FakeCache()
    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        engine = ReasoningEngine()
        await engine._persist(result)
        loaded = await engine.load_from_redis("r1")

    assert loaded is not None
    assert loaded.id == "r1"
    assert loaded.conclusion == "because"


async def test_reflection_engine_decisions_round_trip():
    from apps.core.cognition.reflection_engine import ReflectionEngine

    decisions = [{"rule": "always cite sources", "confidence": 0.8}]
    cache = FakeCache()
    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        engine = ReflectionEngine()
        await engine._persist_decisions(decisions)
        loaded = await engine.load_decisions()

    assert loaded == decisions


async def test_world_state_persist_and_load_round_trip():
    from apps.core.cognition.world_state import WorldState

    ws = WorldState()
    ws._state = {"projects": {"p1": {}}, "tasks": {}}
    ws._dirty = True

    cache = FakeCache()
    fake_db = MagicMock()
    fake_table = MagicMock()
    # create_client() returns a SYNC supabase client — .execute() is a plain
    # method, not a coroutine. A previous version of this test used AsyncMock
    # here, which would have masked the real "await <sync result>" bug.
    fake_table.upsert.return_value.execute = MagicMock(return_value=None)
    fake_db.table.return_value = fake_table

    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
    ):
        await ws.persist()

        ws2 = WorldState()
        loaded = await ws2.load()

    assert loaded is True
    assert ws2._state["projects"] == {"p1": {}}
    # db.table(...) must actually be reachable (no AttributeError) and used.
    fake_db.table.assert_called_with("aria_world_state")
    fake_table.upsert.assert_called_once()


async def test_episodic_memory_persist_episode_does_not_await_sync_execute():
    """_persist_episode used to do `await db.table(...).insert(...).execute()` —
    but create_client() returns a SYNCHRONOUS supabase client, so .execute()
    isn't a coroutine. Awaiting a plain APIResponse object raised TypeError on
    every call, silently swallowed, so episodes were never actually persisted
    to Supabase."""
    from apps.core.cognition.episodic_memory import EpisodicMemory

    fake_db = MagicMock()
    fake_table = MagicMock()
    fake_table.insert.return_value.execute = MagicMock(return_value=None)
    fake_db.table.return_value = fake_table

    episode = {
        "id": "ep1",
        "type": "conversation",
        "content": "user asked about pricing",
        "timestamp": "2026-01-01T00:00:00Z",
    }

    with patch("apps.core.memory.supabase_client.get_db", return_value=fake_db):
        mem = EpisodicMemory()
        await mem._persist_episode("user-1", episode)

    fake_db.table.assert_called_with("aria_episodic_memory")
    inserted = fake_table.insert.call_args[0][0]
    assert inserted["user_id"] == "user-1"
    assert inserted["content"] == "user asked about pricing"
    fake_table.insert.return_value.execute.assert_called_once()


async def test_episodic_memory_store_and_recall_round_trip_is_per_user():
    """Storage moved from a per-process Python list (which doesn't survive
    Fly.io's multi-machine autoscaling — a different request can land on a
    different machine with no shared memory) to per-user Redis keys. Verify
    the round trip actually works, and that one user's episodes never leak
    into another user's recall."""
    from apps.core.cognition.episodic_memory import EpisodicMemory

    cache = FakeCache()
    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch("apps.core.memory.supabase_client.get_db", return_value=None),
    ):
        mem = EpisodicMemory()
        await mem.store_conversation("user-a", "what's the pricing?", "here's our pricing...")
        await mem.store_conversation("user-b", "how's the weather?", "sunny today")

        a_recent = await mem.get_recent("user-a", n=10)
        b_recent = await mem.get_recent("user-b", n=10)

    assert len(a_recent) == 1
    assert "pricing" in a_recent[0]["content"]
    assert len(b_recent) == 1
    assert "weather" in b_recent[0]["content"]


async def test_semantic_memory_load_fact_round_trips():
    from apps.core.memory.semantic_memory import Fact, SemanticMemory

    fact = Fact(
        id="f1",
        content="user prefers dark mode",
        category="user_preference",
        source="chat",
        confidence=0.95,
        embedding=[],
        tags=[],
        created_at="2026-01-01T00:00:00Z",
        accessed_at="2026-01-01T00:00:00Z",
    )

    cache = FakeCache()
    await cache.set("aria:semantic:f1", json.dumps(fact.to_dict()), ttl_seconds=3600)

    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        mem = SemanticMemory()
        loaded = await mem._load_fact_from_redis("f1")

    assert loaded is not None
    assert loaded.content == "user prefers dark mode"


async def test_ariadatabase_has_table_passthrough():
    from apps.core.memory.supabase_client import AriaDatabase

    with patch("apps.core.memory.supabase_client.create_client") as mock_create:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        db = AriaDatabase()
        db.table("some_table")

    mock_client.table.assert_called_once_with("some_table")


@pytest.mark.parametrize(
    "module_path,func_name",
    [
        ("apps.core.intelligence.model_router", "ModelRouter"),
        ("apps.core.intelligence.continuous_learning", "ContinuousLearning"),
    ],
)
async def test_no_bare_ttl_kwarg_left_in_cache_set_calls(module_path, func_name):
    """cache.set(key, value, ttl=...) raises TypeError — AriaCache.set only
    accepts ttl_seconds. Static-scan the source so a future edit can't
    reintroduce the wrong kwarg name silently."""
    import importlib
    import inspect

    module = importlib.import_module(module_path)
    source = inspect.getsource(module)
    assert "ttl=" not in source, f"found bare ttl= kwarg (should be ttl_seconds=) in {module_path}"
