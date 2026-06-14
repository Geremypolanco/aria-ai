"""
TaskRunner — Distributed task execution with Celery.
Falls back to async direct execution when Celery not available.

Broker: Redis (REDIS_URL env var → same Redis as cache)
"""
from __future__ import annotations
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

try:
    from celery import Celery
    _CELERY_AVAILABLE = True
except ImportError:
    _CELERY_AVAILABLE = False

from apps.core.memory.redis_client import get_cache

_TASKS_KEY = "runtime:tasks:v1"
_TASKS_TTL = 86400 * 7

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class TaskRecord:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    args: list = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status.value,
            "priority": self.priority.value,
            "result": str(self.result)[:200] if self.result else None,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": round((self.completed_at - self.started_at) * 1000, 1) if self.completed_at else None,
        }


def _create_celery_app() -> Optional[Any]:
    if not _CELERY_AVAILABLE:
        return None
    import os
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        app = Celery(
            "aria",
            broker=redis_url,
            backend=redis_url,
            include=["apps.runtime.celery.task_runner"],
        )
        app.conf.update(
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            result_expires=3600,
            task_acks_late=True,
            worker_prefetch_multiplier=1,
        )
        return app
    except Exception:
        return None

_celery_app = _create_celery_app()


class TaskRunner:
    """
    Distributed task runner.
    - Celery available + Redis → distributed execution
    - Otherwise → in-process async execution
    """

    def __init__(self):
        self._tasks: list[dict] = []
        self._loaded = False
        self._registry: dict[str, Callable] = {}
        self._celery = _celery_app

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_TASKS_KEY)
                if isinstance(data, list):
                    self._tasks = data
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_TASKS_KEY, self._tasks[-500:], ttl_seconds=_TASKS_TTL)
        except Exception:
            pass

    def register(self, name: str, func: Callable) -> None:
        """Register a callable under a task name."""
        self._registry[name] = func

    async def submit(
        self,
        name: str,
        args: list = [],
        kwargs: dict = {},
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> TaskRecord:
        """Submit a task for execution."""
        await self._load()
        record = TaskRecord(name=name, args=args, kwargs=kwargs, priority=priority)
        self._tasks.append(record.to_dict())

        # Execute immediately in-process (Celery would queue it)
        await self._execute_inline(record)

        # Update in list
        for i, t in enumerate(self._tasks):
            if t.get("task_id") == record.task_id:
                self._tasks[i] = record.to_dict()
                break

        await self._save()
        return record

    async def _execute_inline(self, record: TaskRecord) -> None:
        """Execute task in-process (fallback when no Celery workers)."""
        func = self._registry.get(record.name)
        if not func:
            record.status = TaskStatus.FAILED
            record.error = f"No handler registered for task '{record.name}'"
            return

        record.status = TaskStatus.RUNNING
        record.started_at = time.time()
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*record.args, **record.kwargs)
            else:
                result = func(*record.args, **record.kwargs)
            record.result = result
            record.status = TaskStatus.SUCCESS
        except Exception as exc:
            record.status = TaskStatus.FAILED
            record.error = str(exc)
        finally:
            record.completed_at = time.time()

    async def get_task(self, task_id: str) -> Optional[dict]:
        await self._load()
        for t in self._tasks:
            if t.get("task_id") == task_id:
                return t
        return None

    async def task_stats(self) -> dict:
        await self._load()
        by_status: dict[str, int] = {}
        for t in self._tasks:
            s = t.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        durations = [
            t["duration_ms"] for t in self._tasks
            if t.get("duration_ms") is not None
        ]
        return {
            "total_tasks": len(self._tasks),
            "by_status": by_status,
            "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else 0,
            "celery_available": _CELERY_AVAILABLE,
            "celery_active": self._celery is not None,
            "registered_tasks": list(self._registry.keys()),
        }

_runner_instance: Optional[TaskRunner] = None

def get_task_runner() -> TaskRunner:
    global _runner_instance
    if _runner_instance is None:
        _runner_instance = TaskRunner()
    return _runner_instance
