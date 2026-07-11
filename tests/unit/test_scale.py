"""
Unit tests for the distributed scaling primitives (apps/core/scale/*).

All tests exercise the in-process fallback path (no REDIS_URL), which is the
single-container / CI backend. Redis paths are integration-level and skipped
here. `clock`/`sleep` are injected so bucket pacing and retry backoff are
instant and deterministic.

Covered:
  - task_queue : enqueue → dequeue FIFO, status transitions, depth, BOLA fields
  - rate_limiter: TokenBucket try_acquire + acquire pacing, dispatcher per-provider
  - log_bus    : publish/subscribe in-process fan-out, per-task isolation
  - worker     : handle_task success, permanent failure, transient retry-then-recover
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest


# ── task_queue ────────────────────────────────────────────────────
class TestMissionQueue:
    @pytest.fixture(autouse=True)
    def _clean(self):
        # Reset the module-level in-memory backend between tests.
        from apps.core.scale import task_queue as tq

        tq._mem_pending.clear()
        tq._mem_status.clear()
        yield
        tq._mem_pending.clear()
        tq._mem_status.clear()

    async def test_enqueue_returns_task_id_and_queues(self):
        from apps.core.scale.task_queue import get_queue

        q = get_queue()
        tid = await q.enqueue({"message": "hi"}, user_email="a@b.com")
        assert tid.startswith("task_")
        assert await q.depth() == 1
        status = await q.get_status(tid)
        assert status["state"] == "queued"
        assert status["user_email"] == "a@b.com"
        assert status["payload"] == {"message": "hi"}

    async def test_dequeue_is_fifo(self):
        from apps.core.scale.task_queue import get_queue

        q = get_queue()
        t1 = await q.enqueue({"n": 1})
        t2 = await q.enqueue({"n": 2})
        first = await q.dequeue(timeout=1.0)
        second = await q.dequeue(timeout=1.0)
        assert first["id"] == t1
        assert second["id"] == t2
        assert await q.depth() == 0

    async def test_dequeue_times_out_to_none(self):
        from apps.core.scale.task_queue import get_queue

        q = get_queue()
        got = await q.dequeue(timeout=0.1)
        assert got is None

    async def test_status_transitions(self):
        from apps.core.scale.task_queue import get_queue

        q = get_queue()
        tid = await q.enqueue({"message": "go"})
        await q.set_status(tid, "processing")
        assert (await q.get_status(tid))["state"] == "processing"
        await q.set_status(tid, "completed", result={"reply": "done"})
        done = await q.get_status(tid)
        assert done["state"] == "completed"
        assert done["result"] == {"reply": "done"}

    async def test_invalid_state_rejected(self):
        from apps.core.scale.task_queue import get_queue

        q = get_queue()
        tid = await q.enqueue({})
        with pytest.raises(ValueError):
            await q.set_status(tid, "bogus")

    async def test_get_status_unknown_is_none(self):
        from apps.core.scale.task_queue import get_queue

        assert await get_queue().get_status("task_missing") is None


# ── rate_limiter ──────────────────────────────────────────────────
class _FakeClock:
    """Manually-advanced monotonic clock for deterministic bucket tests."""

    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class TestTokenBucket:
    def test_try_acquire_consumes_capacity_then_fails(self):
        from apps.core.scale.rate_limiter import TokenBucket

        clock = _FakeClock()
        b = TokenBucket(1.0, 3, clock=clock, sleep=None)
        assert b.try_acquire() is True
        assert b.try_acquire() is True
        assert b.try_acquire() is True
        assert b.try_acquire() is False  # capacity exhausted, no time passed

    def test_try_acquire_refills_over_time(self):
        from apps.core.scale.rate_limiter import TokenBucket

        clock = _FakeClock()
        b = TokenBucket(2.0, 2, clock=clock, sleep=None)
        assert b.try_acquire(2) is True
        assert b.try_acquire() is False
        clock.t += 1.0  # 1s * 2 tokens/s = 2 tokens refilled
        assert b.try_acquire() is True
        assert b.try_acquire() is True
        assert b.try_acquire() is False

    async def test_acquire_paces_when_empty(self):
        from apps.core.scale.rate_limiter import TokenBucket

        clock = _FakeClock()
        slept: list[float] = []

        async def fake_sleep(d: float) -> None:
            slept.append(d)
            clock.t += d  # advancing the clock lets the bucket refill

        b = TokenBucket(4.0, 1, clock=clock, sleep=fake_sleep)
        assert await b.acquire() == 0.0  # first token is free (bucket full)
        waited = await b.acquire()  # empty now → must pace
        assert waited > 0.0
        assert slept  # slept at least once
        # deficit 1 token / 4 per sec = 0.25s
        assert abs(waited - 0.25) < 1e-6

    async def test_dispatcher_uses_default_for_unknown_provider(self):
        from apps.core.scale.rate_limiter import RateLimitDispatcher

        disp = RateLimitDispatcher()
        # 'default' capacity is 20 → first acquire is free/instant.
        waited = await disp.acquire("some-unlisted-provider")
        assert waited == 0.0

    async def test_dispatcher_reuses_bucket_per_provider(self):
        from apps.core.scale.rate_limiter import RateLimitDispatcher

        disp = RateLimitDispatcher()
        await disp.acquire("anthropic")
        b1 = disp._bucket("anthropic")
        b2 = disp._bucket("anthropic")
        assert b1 is b2


# ── log_bus ───────────────────────────────────────────────────────
class TestLogBus:
    def test_channel_for(self):
        from apps.core.scale.log_bus import channel_for

        assert channel_for("task_1") == "aria:logs:task_1"

    async def test_publish_reaches_subscriber(self):
        import json

        from apps.core.scale import log_bus

        tid = "task_pub"
        agen = log_bus.subscribe(tid)
        # Prime the subscription (registers the in-process queue).
        sub_task = asyncio.ensure_future(agen.__anext__())
        await asyncio.sleep(0.01)
        await log_bus.publish(tid, "hello", level="ok")
        line = await asyncio.wait_for(sub_task, timeout=1.0)
        data = json.loads(line)
        assert data["msg"] == "hello"
        assert data["level"] == "ok"
        await agen.aclose()

    async def test_subscribers_are_isolated_per_task(self):
        from apps.core.scale import log_bus

        a = log_bus.subscribe("task_a")
        b = log_bus.subscribe("task_b")
        ta = asyncio.ensure_future(a.__anext__())
        tb = asyncio.ensure_future(b.__anext__())
        await asyncio.sleep(0.01)
        await log_bus.publish("task_a", "only-a")
        got = await asyncio.wait_for(ta, timeout=1.0)
        assert "only-a" in got
        assert not tb.done()  # task_b's subscriber saw nothing
        tb.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tb  # let the cancellation settle before closing the generator
        await a.aclose()
        await b.aclose()

    async def test_publish_without_subscriber_is_noop(self):
        from apps.core.scale import log_bus

        # Must not raise when nobody is listening.
        await log_bus.publish("task_nobody", "into the void")


# ── worker ────────────────────────────────────────────────────────
class TestWorker:
    @pytest.fixture(autouse=True)
    def _clean(self):
        from apps.core.scale import task_queue as tq

        tq._mem_pending.clear()
        tq._mem_status.clear()
        yield
        tq._mem_pending.clear()
        tq._mem_status.clear()

    async def test_handle_task_success(self):
        from apps.core.scale.task_queue import MissionQueue
        from apps.core.scale.worker import handle_task

        q = MissionQueue()
        tid = await q.enqueue({"message": "do it", "provider": "default"})
        task = await q.dequeue(timeout=1.0)

        async def fake_agent(payload):
            return {"reply": "ok:" + payload["message"]}

        outcome = await handle_task(task, queue=q, agent_run=fake_agent)
        assert outcome.ok is True
        status = await q.get_status(tid)
        assert status["state"] == "completed"
        assert status["result"] == {"reply": "ok:do it"}

    async def test_handle_task_permanent_failure_no_retry(self):
        from apps.core.scale.task_queue import MissionQueue
        from apps.core.scale.worker import handle_task

        q = MissionQueue()
        tid = await q.enqueue({"message": "bad"})
        task = await q.dequeue(timeout=1.0)
        calls = {"n": 0}

        async def failing_agent(payload):
            calls["n"] += 1
            raise ValueError("invalid input")  # permanent → not retryable

        slept: list[float] = []

        async def fake_sleep(d):
            slept.append(d)

        outcome = await handle_task(task, queue=q, agent_run=failing_agent, sleep=fake_sleep)
        assert outcome.ok is False
        assert calls["n"] == 1  # no retries for a permanent error
        assert slept == []
        assert (await q.get_status(tid))["state"] == "failed"

    async def test_handle_task_transient_then_recovers(self):
        from apps.core.scale.task_queue import MissionQueue
        from apps.core.scale.worker import handle_task

        q = MissionQueue()
        tid = await q.enqueue({"message": "retry-me"})
        task = await q.dequeue(timeout=1.0)
        calls = {"n": 0}

        async def flaky_agent(payload):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("connection timed out")  # transient
            return {"reply": "recovered"}

        slept: list[float] = []

        async def fake_sleep(d):
            slept.append(d)

        outcome = await handle_task(
            task, queue=q, agent_run=flaky_agent, delays=(5, 15, 30), sleep=fake_sleep
        )
        assert outcome.ok is True
        assert calls["n"] == 2  # failed once, recovered on retry
        assert slept == [5]  # one backoff of 5s
        assert (await q.get_status(tid))["state"] == "completed"
