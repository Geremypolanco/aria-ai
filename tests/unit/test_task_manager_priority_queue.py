"""Regression test: TaskManager advertised priority queuing (submit()'s
`priority: int = 5  # 1=highest, 10=lowest` param, items enqueued as
(priority, timestamp, task_id, coro_factory) tuples) but backed it with a
plain asyncio.Queue — a FIFO queue that does not sort by the tuple's first
element. Only asyncio.PriorityQueue (heapq-backed) does that. This silently
ignored the priority parameter entirely; every task ran in submission order
regardless of stated priority.
"""

from __future__ import annotations

import asyncio

import pytest

from apps.core.tools.task_manager import TaskManager

pytestmark = pytest.mark.asyncio


async def test_queue_is_a_priority_queue():
    mgr = TaskManager()
    assert isinstance(mgr._queue, asyncio.PriorityQueue)


async def test_lower_priority_number_is_dequeued_first():
    mgr = TaskManager()
    await mgr._queue.put((5, 1.0, "low-priority-task", None))
    await mgr._queue.put((1, 2.0, "high-priority-task", None))
    await mgr._queue.put((3, 3.0, "mid-priority-task", None))

    first = await mgr._queue.get()
    second = await mgr._queue.get()
    third = await mgr._queue.get()

    assert first[2] == "high-priority-task"
    assert second[2] == "mid-priority-task"
    assert third[2] == "low-priority-task"
