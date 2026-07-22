"""Regression test: TaskManager's retry mechanism re-queued the exact same
already-awaited coroutine object. A coroutine can only be awaited once — the
retry attempt raised RuntimeError("cannot reuse already awaited coroutine")
instead of actually re-running the task, and that RuntimeError (not the real
failure) is what ended up in record.error once retries were exhausted.
Verified live: awaiting the same coroutine object twice raises exactly that
RuntimeError. Fixed by taking a coroutine *factory* (submit(coro_factory=...))
so each attempt gets a fresh coroutine.
"""

from __future__ import annotations

import asyncio

import pytest

from apps.core.tools.task_manager import TaskManager, TaskStatus

pytestmark = pytest.mark.asyncio


async def _wait_until(predicate, timeout=5.0, interval=0.02):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


async def test_retry_actually_reruns_and_can_succeed():
    mgr = TaskManager()
    attempts = {"count": 0}

    async def flaky():
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise ValueError("transient failure")
        return "ok on second try"

    task_id = await mgr.submit("flaky task", flaky, priority=1)
    ok = await _wait_until(lambda: mgr.get_task(task_id).status == TaskStatus.DONE)
    assert ok, f"task never completed, final state: {mgr.get_task(task_id)}"
    record = mgr.get_task(task_id)
    assert attempts["count"] == 2
    assert record.result == "ok on second try"
    assert "cannot reuse already awaited coroutine" not in (record.error or "")


async def test_final_failure_surfaces_the_real_error_not_a_coroutine_reuse_error():
    mgr = TaskManager()

    async def always_fails():
        raise ValueError("the real underlying reason")

    task_id = await mgr.submit("always fails", always_fails, priority=1)
    ok = await _wait_until(lambda: mgr.get_task(task_id).status == TaskStatus.FAILED, timeout=10.0)
    assert ok, f"task never reached FAILED, final state: {mgr.get_task(task_id)}"
    record = mgr.get_task(task_id)
    assert "the real underlying reason" in record.error
    assert "cannot reuse already awaited coroutine" not in record.error
