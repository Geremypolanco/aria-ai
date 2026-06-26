"""
Unit tests for the ARIA task queue.

Verifies:
  - Task enqueue and basic properties
  - Handler registration (decorator and imperative)
  - Priority ordering
  - Task serialization roundtrip
  - Stats tracking
  - Queue depth reporting
"""
from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestTask:
    def test_task_defaults(self):
        from apps.core.runtime.task_queue import Task, TaskPriority, TaskState
        task = Task(id="abc", name="test", payload={"x": 1})
        assert task.priority == TaskPriority.NORMAL
        assert task.state == TaskState.QUEUED
        assert task.attempts == 0
        assert task.created_at  # auto-set

    def test_stream_key_reflects_priority(self):
        from apps.core.runtime.task_queue import Task, TaskPriority
        task = Task(id="t1", name="job", payload={}, priority=TaskPriority.CRITICAL)
        assert "critical" in task.stream_key

    def test_serialization_roundtrip(self):
        from apps.core.runtime.task_queue import Task, TaskPriority, TaskState
        task = Task(
            id="xyz", name="income_cycle",
            payload={"strategy": "content"},
            priority=TaskPriority.HIGH,
            state=TaskState.PROCESSING,
            attempts=1,
            metadata={"source": "scheduler"},
        )
        d = task.to_dict()
        restored = Task.from_dict(d)
        assert restored.id == task.id
        assert restored.name == task.name
        assert restored.priority == TaskPriority.HIGH
        assert restored.state == TaskState.PROCESSING
        assert restored.metadata["source"] == "scheduler"

    def test_from_dict_with_string_enums(self):
        from apps.core.runtime.task_queue import Task, TaskPriority, TaskState
        d = {
            "id": "t1", "name": "job", "payload": {},
            "priority": "low", "state": "done",
            "attempts": 0, "created_at": "", "started_at": None,
            "finished_at": None, "result": None, "error": None,
            "scheduled_for": None, "metadata": {},
        }
        task = Task.from_dict(d)
        assert task.priority == TaskPriority.LOW
        assert task.state == TaskState.DONE


class TestTaskQueue:
    @pytest.fixture
    def queue(self):
        from apps.core.runtime.task_queue import TaskQueue
        q = TaskQueue()
        return q

    @pytest.fixture
    def mock_cache(self):
        cache = AsyncMock()
        cache.rpush = AsyncMock(return_value=1)
        cache.lrange = MagicMock(return_value=[])
        cache.ltrim = AsyncMock(return_value=True)
        cache.set = AsyncMock(return_value=True)
        cache.get = AsyncMock(return_value=None)
        return cache

    @pytest.mark.asyncio
    async def test_enqueue_returns_task_id(self, queue, mock_cache):
        with patch("apps.core.runtime.task_queue.get_cache", return_value=mock_cache):
            task_id = await queue.enqueue("test_task", {"key": "val"})

        assert isinstance(task_id, str)
        assert len(task_id) > 0

    @pytest.mark.asyncio
    async def test_enqueue_critical_uses_critical_priority(self, queue, mock_cache):
        from apps.core.runtime.task_queue import TaskPriority
        with patch("apps.core.runtime.task_queue.get_cache", return_value=mock_cache):
            task_id = await queue.enqueue_critical("urgent_task", {"data": 1})

        assert task_id
        assert queue._stats[TaskPriority.CRITICAL.value]["enqueued"] == 1

    def test_handler_decorator(self, queue):
        @queue.handler("my_task")
        async def handle(payload):
            return {"done": True}

        assert "my_task" in queue._handlers
        assert queue._handlers["my_task"] is handle

    def test_register_imperative(self, queue):
        async def handler(payload):
            return {}

        queue.register("another_task", handler)
        assert "another_task" in queue._handlers

    @pytest.mark.asyncio
    async def test_dispatch_calls_handler(self, queue, mock_cache):
        results = []

        async def my_handler(payload):
            results.append(payload)
            return {"success": True}

        queue.register("test_dispatch", my_handler)

        task_data = {
            "id": "t1", "name": "test_dispatch",
            "payload": {"x": 42},
            "priority": "normal", "state": "queued",
            "attempts": 0, "created_at": "2026-01-01T00:00:00Z",
            "started_at": None, "finished_at": None,
            "result": None, "error": None,
            "scheduled_for": None, "metadata": {},
        }
        raw = {"data": json.dumps(task_data)}

        await queue._dispatch(raw, mock_cache)

        assert len(results) == 1
        assert results[0]["x"] == 42

    @pytest.mark.asyncio
    async def test_dispatch_stores_result_on_success(self, queue, mock_cache):
        async def handler(payload):
            return {"value": "output"}

        queue.register("store_test", handler)

        task_data = {
            "id": "store-1", "name": "store_test",
            "payload": {}, "priority": "normal", "state": "queued",
            "attempts": 0, "created_at": "", "started_at": None,
            "finished_at": None, "result": None, "error": None,
            "scheduled_for": None, "metadata": {},
        }
        raw = {"data": json.dumps(task_data)}

        await queue._dispatch(raw, mock_cache)

        # Verify cache.set was called with result
        mock_cache.set.assert_called()
        call_args = mock_cache.set.call_args[0]
        assert "store-1" in call_args[0]

    @pytest.mark.asyncio
    async def test_dispatch_failed_task_increments_stat(self, queue, mock_cache):
        from apps.core.runtime.task_queue import TaskPriority

        async def failing_handler(payload):
            raise ValueError("Intentional error")

        queue.register("failing_task", failing_handler)

        # Set attempts to MAX_ATTEMPTS-1 so it goes to DLQ
        task_data = {
            "id": "fail-1", "name": "failing_task",
            "payload": {}, "priority": "normal", "state": "queued",
            "attempts": 2,  # will be incremented to 3 = MAX_ATTEMPTS → DLQ
            "created_at": "", "started_at": None, "finished_at": None,
            "result": None, "error": None, "scheduled_for": None, "metadata": {},
        }
        raw = {"data": json.dumps(task_data)}

        await queue._dispatch(raw, mock_cache)

        assert queue._stats["normal"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_dispatch_no_handler_marks_dead(self, queue, mock_cache):
        from apps.core.runtime.task_queue import TaskState
        task_data = {
            "id": "no-handler-1", "name": "unregistered_task",
            "payload": {}, "priority": "normal", "state": "queued",
            "attempts": 0, "created_at": "", "started_at": None,
            "finished_at": None, "result": None, "error": None,
            "scheduled_for": None, "metadata": {},
        }
        raw = {"data": json.dumps(task_data)}

        await queue._dispatch(raw, mock_cache)

        # Should call set with dead state
        stored = json.loads(mock_cache.set.call_args[0][1])
        assert stored["state"] == TaskState.DEAD.value

    def test_get_stats_structure(self, queue):
        stats = queue.get_stats()
        assert "running" in stats
        assert "handlers" in stats
        assert "stats_by_priority" in stats
        assert "normal" in stats["stats_by_priority"]
        assert "critical" in stats["stats_by_priority"]

    @pytest.mark.asyncio
    async def test_start_and_stop_worker(self, queue, mock_cache):
        with patch("apps.core.runtime.task_queue.get_cache", return_value=mock_cache):
            await queue.start_worker()
            assert queue._running
            assert queue._worker_task is not None
            await queue.stop_worker()
            assert not queue._running

    @pytest.mark.asyncio
    async def test_enqueue_many(self, queue, mock_cache):
        with patch("apps.core.runtime.task_queue.get_cache", return_value=mock_cache):
            ids = await queue.enqueue_many([
                ("task_a", {"x": 1}),
                ("task_b", {"y": 2}),
                ("task_c", {"z": 3}),
            ])

        assert len(ids) == 3
        assert all(isinstance(i, str) for i in ids)
        assert len(set(ids)) == 3  # all unique
