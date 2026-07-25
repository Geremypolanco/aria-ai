"""Unit tests for apps/core/safety/hitl_queue.py — the escalation queue that
replaced guardrails Layer 2's flat "declined" apology with a real path back
to a human decision (see aria_mind.py's Layer 2 block branch)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.safety.hitl_queue import HitlQueueStore

pytestmark = pytest.mark.asyncio


def _mock_cache_that_fails():
    """Simulates Redis being unreachable — every call raises, matching a real
    network failure rather than a clean None/False return."""
    cache = MagicMock()
    cache.set = AsyncMock(side_effect=RuntimeError("upstash unreachable"))
    cache.rpush = AsyncMock(side_effect=RuntimeError("upstash unreachable"))
    cache.ltrim = AsyncMock(side_effect=RuntimeError("upstash unreachable"))
    cache.get = AsyncMock(side_effect=RuntimeError("upstash unreachable"))
    cache.lrange = AsyncMock(side_effect=RuntimeError("upstash unreachable"))
    cache.acquire_lock = AsyncMock(return_value=True)
    cache.release_lock = AsyncMock(return_value=True)
    return cache


async def test_enqueue_returns_a_pending_request():
    store = HitlQueueStore()
    req = await store.enqueue(
        chat_id="chat-1",
        email="buyer@example.com",
        user_text="buy video credits",
        tool="provision_b2b_payment",
        tool_args={"amount_usd": 1200},
        risk_score=0.81,
        risk_reason="unfamiliar vendor",
    )
    assert req.request_id.startswith("req_")
    assert req.status == "pending"
    assert req.risk_score == 0.81


async def test_enqueue_and_list_pending_work_without_redis():
    """Redis being unreachable must not lose the request — the process-local
    dict is the source of truth, Redis persistence is best-effort on top."""
    store = HitlQueueStore()
    with patch.object(store, "_cache", AsyncMock(return_value=_mock_cache_that_fails())):
        req = await store.enqueue(
            chat_id="chat-1",
            email="buyer@example.com",
            user_text="buy video credits",
            tool="provision_b2b_payment",
            tool_args={"amount_usd": 1200},
            risk_score=0.81,
            risk_reason="unfamiliar vendor",
        )
        pending = await store.list_pending()

    assert any(r.request_id == req.request_id for r in pending)


async def test_list_pending_sorts_highest_risk_first():
    store = HitlQueueStore()
    await store.enqueue(
        chat_id="c1",
        email="a@x.com",
        user_text="x",
        tool="t1",
        tool_args={},
        risk_score=0.42,
        risk_reason="low",
    )
    await store.enqueue(
        chat_id="c2",
        email="a@x.com",
        user_text="x",
        tool="t2",
        tool_args={},
        risk_score=0.81,
        risk_reason="high",
    )
    pending = await store.list_pending()
    assert pending[0].risk_score == 0.81
    assert pending[1].risk_score == 0.42


async def test_resolve_approve_marks_approved():
    store = HitlQueueStore()
    req = await store.enqueue(
        chat_id="c1",
        email="a@x.com",
        user_text="x",
        tool="t1",
        tool_args={"a": 1},
        risk_score=0.7,
        risk_reason="r",
    )
    resolved = await store.resolve(req.request_id, decision="approve", resolved_by="owner@x.com")
    assert resolved.status == "approved"
    assert resolved.resolved_by == "owner@x.com"
    assert resolved.resolved_at is not None


async def test_resolve_modify_replaces_tool_args():
    store = HitlQueueStore()
    req = await store.enqueue(
        chat_id="c1",
        email="a@x.com",
        user_text="x",
        tool="t1",
        tool_args={"amount_usd": 500},
        risk_score=0.7,
        risk_reason="r",
    )
    resolved = await store.resolve(
        req.request_id,
        decision="modify",
        resolved_by="owner@x.com",
        modified_args={"amount_usd": 150},
    )
    assert resolved.status == "modified"
    assert resolved.tool_args == {"amount_usd": 150}


async def test_resolve_deny_does_not_touch_tool_args():
    store = HitlQueueStore()
    req = await store.enqueue(
        chat_id="c1",
        email="a@x.com",
        user_text="x",
        tool="t1",
        tool_args={"amount_usd": 500},
        risk_score=0.7,
        risk_reason="r",
    )
    resolved = await store.resolve(req.request_id, decision="deny", resolved_by="owner@x.com")
    assert resolved.status == "denied"
    assert resolved.tool_args == {"amount_usd": 500}


async def test_resolve_twice_second_call_returns_none():
    """The real regression this guards against: a double-click (or a retried
    network request) must not execute the underlying action twice."""
    store = HitlQueueStore()
    req = await store.enqueue(
        chat_id="c1",
        email="a@x.com",
        user_text="x",
        tool="t1",
        tool_args={},
        risk_score=0.7,
        risk_reason="r",
    )
    first = await store.resolve(req.request_id, decision="approve", resolved_by="owner@x.com")
    second = await store.resolve(req.request_id, decision="approve", resolved_by="owner@x.com")
    assert first is not None
    assert second is None


async def test_resolve_unknown_request_returns_none():
    store = HitlQueueStore()
    resolved = await store.resolve(
        "req_doesnotexist", decision="approve", resolved_by="owner@x.com"
    )
    assert resolved is None


async def test_resolve_invalid_decision_raises():
    store = HitlQueueStore()
    req = await store.enqueue(
        chat_id="c1",
        email="a@x.com",
        user_text="x",
        tool="t1",
        tool_args={},
        risk_score=0.7,
        risk_reason="r",
    )
    with pytest.raises(ValueError):
        await store.resolve(
            req.request_id, decision="approve_with_extreme_prejudice", resolved_by="x"
        )


async def test_record_result_only_reflects_a_real_outcome():
    store = HitlQueueStore()
    req = await store.enqueue(
        chat_id="c1",
        email="a@x.com",
        user_text="x",
        tool="t1",
        tool_args={},
        risk_score=0.7,
        risk_reason="r",
    )
    assert req.result_text is None
    await store.record_result(req.request_id, "Flash sale created: 25% off, id sale_123")
    fetched = await store.get(req.request_id)
    assert fetched.result_text == "Flash sale created: 25% off, id sale_123"
