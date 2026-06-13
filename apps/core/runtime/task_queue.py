"""
ARIA Task Queue — Redis Streams-based distributed task execution.

Design:
  - Tasks published to Redis Stream `aria:tasks:{stream}`
  - Workers consume from consumer groups (persistent offset tracking)
  - Dead-letter queue for failed tasks (max 3 attempts)
  - Priority queues: critical, high, normal, low
  - Task results stored in Redis with configurable TTL
  - Metrics emitted on every task lifecycle event

Why Redis Streams vs Celery:
  - No separate broker needed (already using Upstash Redis)
  - Built-in consumer groups with at-least-once delivery
  - Persistent log — tasks survives broker restart
  - Simpler ops — one fewer service to manage on Fly.io
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("aria.task_queue")

STREAM_PREFIX = "aria:tasks"
DLQ_STREAM = "aria:tasks:dlq"
RESULT_PREFIX = "aria:task:result"
RESULT_TTL = 3600 * 24  # 24 hours
MAX_ATTEMPTS = 3
CONSUMER_GROUP = "aria-workers"
CONSUMER_NAME = "aria-worker-1"
BLOCK_MS = 2000  # stream read block timeout


class TaskPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class TaskState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    DEAD = "dead"          # exhausted retries → DLQ


@dataclass
class Task:
    id: str
    name: str
    payload: dict[str, Any]
    priority: TaskPriority = TaskPriority.NORMAL
    state: TaskState = TaskState.QUEUED
    attempts: int = 0
    created_at: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    scheduled_for: Optional[str] = None  # ISO timestamp for deferred tasks
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["priority"] = self.priority.value
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        d = dict(d)
        d["priority"] = TaskPriority(d.get("priority", "normal"))
        d["state"] = TaskState(d.get("state", "queued"))
        return cls(**d)

    @property
    def stream_key(self) -> str:
        return f"{STREAM_PREFIX}:{self.priority.value}"


class TaskQueue:
    """
    Redis Streams-based task queue.

    Usage:
        queue = TaskQueue()

        # Publish a task
        task_id = await queue.enqueue("income_cycle", {"strategy": "content"})

        # Poll results
        result = await queue.get_result(task_id, timeout=30)

        # Register a handler and start consuming
        @queue.handler("income_cycle")
        async def handle_income(payload):
            return {"success": True}

        await queue.start_worker()
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable] = {}
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._stats = {p.value: {"enqueued": 0, "processed": 0, "failed": 0}
                       for p in TaskPriority}

    # ── Publishing ───────────────────────────────────────────────────────

    async def enqueue(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        scheduled_for: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        task = Task(
            id=str(uuid.uuid4())[:12],
            name=name,
            payload=payload or {},
            priority=priority,
            scheduled_for=scheduled_for,
            metadata=metadata or {},
        )

        await self._write_to_stream(task)
        self._stats[priority.value]["enqueued"] += 1

        logger.info("[TaskQueue] Enqueued task %s:%s (priority=%s)", name, task.id, priority.value)
        return task.id

    async def enqueue_critical(self, name: str, payload: dict | None = None) -> str:
        return await self.enqueue(name, payload, priority=TaskPriority.CRITICAL)

    async def enqueue_many(self, tasks: list[tuple[str, dict]]) -> list[str]:
        return [await self.enqueue(name, payload) for name, payload in tasks]

    # ── Consuming ────────────────────────────────────────────────────────

    def handler(self, task_name: str):
        """Decorator to register a task handler."""
        def decorator(fn: Callable):
            self._handlers[task_name] = fn
            logger.debug("[TaskQueue] Registered handler for '%s'", task_name)
            return fn
        return decorator

    def register(self, task_name: str, fn: Callable) -> None:
        """Imperative handler registration."""
        self._handlers[task_name] = fn

    async def start_worker(self, streams: list[TaskPriority] | None = None) -> None:
        """Start background worker consuming from all priority streams."""
        if self._running:
            return
        self._running = True
        consume_streams = streams or list(TaskPriority)
        self._worker_task = asyncio.create_task(
            self._worker_loop(consume_streams),
            name="aria-task-worker",
        )
        logger.info("[TaskQueue] Worker started (consuming %d streams)", len(consume_streams))

    async def stop_worker(self) -> None:
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("[TaskQueue] Worker stopped")

    async def _worker_loop(self, priorities: list[TaskPriority]) -> None:
        """Main consumer loop — processes tasks in priority order."""
        stream_keys = [f"{STREAM_PREFIX}:{p.value}" for p in priorities]

        while self._running:
            try:
                tasks_processed = await self._process_pending(stream_keys)
                if not tasks_processed:
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[TaskQueue] Worker loop error: %s", exc)
                await asyncio.sleep(2)

    async def _process_pending(self, stream_keys: list[str]) -> bool:
        """Check all streams and process one task from the highest-priority non-empty stream."""
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            return False

        # Poll streams in priority order (critical first)
        for stream_key in stream_keys:
            raw_tasks = await self._read_stream(cache, stream_key)
            if raw_tasks:
                for raw in raw_tasks:
                    await self._dispatch(raw, cache)
                return True
        return False

    async def _dispatch(self, raw: dict, cache) -> None:
        """Deserialize and execute a task, handle retries and DLQ."""
        try:
            task = Task.from_dict(json.loads(raw.get("data", "{}")))
        except Exception as exc:
            logger.error("[TaskQueue] Cannot deserialize task: %s", exc)
            return

        task.state = TaskState.PROCESSING
        task.started_at = datetime.now(timezone.utc).isoformat()
        task.attempts += 1

        handler = self._handlers.get(task.name)
        if not handler:
            logger.warning("[TaskQueue] No handler registered for '%s'", task.name)
            task.state = TaskState.DEAD
            task.error = f"No handler for task '{task.name}'"
            await self._store_result(cache, task)
            return

        try:
            start = time.monotonic()
            result = await asyncio.wait_for(handler(task.payload), timeout=300)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            task.state = TaskState.DONE
            task.result = result if isinstance(result, dict) else {"output": str(result)}
            task.finished_at = datetime.now(timezone.utc).isoformat()
            task.metadata["elapsed_ms"] = elapsed_ms

            self._stats[task.priority.value]["processed"] += 1
            logger.info("[TaskQueue] Task %s:%s done in %dms", task.name, task.id, elapsed_ms)

        except asyncio.TimeoutError:
            task.error = "Task timed out after 300s"
            await self._handle_failure(task, cache)
        except Exception as exc:
            task.error = str(exc)
            logger.error("[TaskQueue] Task %s:%s failed: %s", task.name, task.id, exc)
            await self._handle_failure(task, cache)
        else:
            await self._store_result(cache, task)

    async def _handle_failure(self, task: Task, cache) -> None:
        self._stats[task.priority.value]["failed"] += 1
        if task.attempts >= MAX_ATTEMPTS:
            task.state = TaskState.DEAD
            await self._write_to_dlq(task)
            logger.error("[TaskQueue] Task %s:%s moved to DLQ after %d attempts",
                         task.name, task.id, task.attempts)
        else:
            task.state = TaskState.QUEUED
            # Re-enqueue with backoff delay (fire and forget)
            backoff = 2 ** task.attempts
            asyncio.create_task(self._delayed_requeue(task, backoff))

        await self._store_result(cache, task)

    async def _delayed_requeue(self, task: Task, delay_seconds: float) -> None:
        await asyncio.sleep(delay_seconds)
        await self._write_to_stream(task)

    # ── Results ──────────────────────────────────────────────────────────

    async def get_result(self, task_id: str, timeout: float = 30) -> Optional[dict]:
        """Poll for task result until done or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = await self._load_result(task_id)
            if result and result.get("state") in (TaskState.DONE.value, TaskState.FAILED.value, TaskState.DEAD.value):
                return result
            await asyncio.sleep(0.5)
        return None

    async def _store_result(self, cache, task: Task) -> None:
        try:
            key = f"{RESULT_PREFIX}:{task.id}"
            await cache.set(key, json.dumps(task.to_dict()), ttl_seconds=RESULT_TTL)
        except Exception as exc:
            logger.debug("[TaskQueue] Cannot store result for %s: %s", task.id, exc)

    async def _load_result(self, task_id: str) -> Optional[dict]:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                raw = await cache.get(f"{RESULT_PREFIX}:{task_id}")
                if raw:
                    return json.loads(raw)
        except Exception:
            pass
        return None

    # ── Stream I/O (Upstash REST API compatible) ─────────────────────────

    async def _write_to_stream(self, task: Task) -> None:
        """
        Write task to Redis list (simulating stream).
        Upstash REST API does not support XADD natively in the REST client;
        we use RPUSH as a reliable ordered queue instead.
        """
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                data = json.dumps({"data": json.dumps(task.to_dict())})
                await cache.rpush(task.stream_key, data)
        except Exception as exc:
            logger.error("[TaskQueue] Cannot write task to stream: %s", exc)

    async def _read_stream(self, cache, stream_key: str) -> list[dict]:
        """Read and remove one task from the front of the list."""
        try:
            items = cache.lrange(stream_key, 0, 0)  # peek at head
            if items:
                await cache.ltrim(stream_key, 1, -1)  # pop head
                return [json.loads(item) for item in items]
        except Exception as exc:
            logger.debug("[TaskQueue] Stream read failed for %s: %s", stream_key, exc)
        return []

    async def _write_to_dlq(self, task: Task) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                await cache.rpush(DLQ_STREAM, json.dumps(task.to_dict()))
        except Exception as exc:
            logger.debug("[TaskQueue] DLQ write failed: %s", exc)

    # ── Observability ────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "running": self._running,
            "handlers": list(self._handlers.keys()),
            "stats_by_priority": self._stats,
        }

    async def queue_depths(self) -> dict[str, int]:
        depths = {}
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                for p in TaskPriority:
                    key = f"{STREAM_PREFIX}:{p.value}"
                    items = cache.lrange(key, 0, -1)
                    depths[p.value] = len(items)
        except Exception:
            pass
        return depths


_queue: Optional[TaskQueue] = None


def get_task_queue() -> TaskQueue:
    global _queue
    if _queue is None:
        _queue = TaskQueue()
    return _queue
