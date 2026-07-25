"""Regression test: worker._next_task() raced an in-flight dequeue() against
`stop.wait()` via asyncio.wait(..., return_when=FIRST_COMPLETED), then checked
`if stopper in done` FIRST. When both futures completed in the same event-loop
tick — a task got popped off the queue in the exact instant `stop` was also
set — the old code took the "stop requested" branch regardless, cancelled a
future that was already done (a no-op), awaited it inside a broad
suppress(Exception), and then unconditionally `return None`d — silently
dropping a task that had already been removed from Redis/memory with no
requeue path. Fixed to check `deq in done` first and return its result
whenever the dequeue actually completed, even if stop fired at the same time."""

from __future__ import annotations

import asyncio

import pytest

from apps.core.scale.worker import _next_task

pytestmark = pytest.mark.asyncio


async def test_next_task_does_not_drop_a_task_dequeued_in_the_same_instant_stop_fires():
    stop = asyncio.Event()

    class FakeQueue:
        async def dequeue(self, timeout):
            # stop becomes set() in the same tick dequeue() resolves — the
            # exact race: both futures are done when asyncio.wait returns.
            stop.set()
            return {"id": "mission-1"}

    result = await _next_task(FakeQueue(), stop, poll=1.0)
    assert result == {"id": "mission-1"}


async def test_next_task_returns_none_when_stop_fires_with_nothing_dequeued():
    stop = asyncio.Event()

    class NeverResolvingQueue:
        async def dequeue(self, timeout):
            await asyncio.sleep(10)
            return {"id": "should-never-be-reached"}

    stop.set()
    result = await asyncio.wait_for(_next_task(NeverResolvingQueue(), stop, poll=1.0), timeout=2)
    assert result is None


async def test_next_task_returns_dequeued_task_when_stop_never_fires():
    stop = asyncio.Event()

    class FakeQueue:
        async def dequeue(self, timeout):
            return {"id": "mission-2"}

    result = await _next_task(FakeQueue(), stop, poll=1.0)
    assert result == {"id": "mission-2"}
