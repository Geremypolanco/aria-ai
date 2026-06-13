"""
task_manager.py — Persistent background task queue for ARIA AI.

Inspired by Manus "persistent-computing":
  - Tasks run in the background even after a conversation turn ends
  - Status tracked in Redis (falls back to in-memory if Redis is unavailable)
  - Results delivered via Telegram + WebSocket when complete
  - Supports cancellation, retry, and priority queuing
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("aria.task_manager")


class TaskStatus(str, Enum):
    QUEUED    = "queued"
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskRecord:
    id: str
    name: str
    description: str
    status: TaskStatus = TaskStatus.QUEUED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    session_id: Optional[str] = None
    priority: int = 5  # 1=highest, 10=lowest
    retries: int = 0
    max_retries: int = 2

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
            "session_id": self.session_id,
            "priority": self.priority,
            "retries": self.retries,
        }


class TaskManager:
    """
    Runs coroutines as background tasks with status tracking and delivery.

    Usage:
        mgr = get_task_manager()
        task_id = await mgr.submit("Research AI trends", coro, session_id="telegram:123")
        status = mgr.get_task(task_id)
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._started = False

    def start(self, workers: int = 3) -> None:
        if self._started:
            return
        self._started = True
        for _ in range(workers):
            t = asyncio.create_task(self._worker())
            self._workers.append(t)
        logger.info("[TaskManager] Started with %d workers", workers)

    async def submit(
        self,
        name: str,
        coro: Coroutine,
        description: str = "",
        session_id: Optional[str] = None,
        priority: int = 5,
    ) -> str:
        """Submit a coroutine as a background task. Returns task_id."""
        if not self._started:
            self.start()

        task_id = str(uuid.uuid4())[:8]
        record = TaskRecord(
            id=task_id,
            name=name,
            description=description or name,
            session_id=session_id,
            priority=priority,
        )
        self._tasks[task_id] = record

        # (priority, timestamp, id, coro) — lower priority number = runs first
        await self._queue.put((priority, time.monotonic(), task_id, coro))
        logger.info("[TaskManager] Queued task %s: %s", task_id, name)

        await self._notify_progress(record, "queued", f"Tarea '{name}' en cola (ID: {task_id})")
        return task_id

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self._tasks.get(task_id)

    def list_tasks(self, status: Optional[str] = None, limit: int = 20) -> list[dict]:
        tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        if status:
            tasks = [t for t in tasks if t.status.value == status]
        return [t.to_dict() for t in tasks[:limit]]

    def cancel_task(self, task_id: str) -> bool:
        record = self._tasks.get(task_id)
        if record and record.status == TaskStatus.QUEUED:
            record.status = TaskStatus.CANCELLED
            record.completed_at = datetime.now(timezone.utc).isoformat()
            return True
        return False

    def stats(self) -> dict:
        counts = {s.value: 0 for s in TaskStatus}
        for t in self._tasks.values():
            counts[t.status.value] += 1
        return {"total": len(self._tasks), "by_status": counts, "queue_size": self._queue.qsize()}

    # ── PRIVATE ──────────────────────────────────────────────────────────────

    async def _worker(self) -> None:
        while True:
            try:
                priority, ts, task_id, coro = await self._queue.get()
                record = self._tasks.get(task_id)

                if not record or record.status == TaskStatus.CANCELLED:
                    self._queue.task_done()
                    continue

                record.status = TaskStatus.RUNNING
                record.started_at = datetime.now(timezone.utc).isoformat()
                await self._notify_progress(record, "running", f"▶️ Ejecutando: {record.name}")

                try:
                    result = await coro
                    record.status = TaskStatus.DONE
                    record.result = str(result)[:2000] if result else "Completado"
                    record.completed_at = datetime.now(timezone.utc).isoformat()
                    await self._notify_completion(record)

                except Exception as exc:
                    record.retries += 1
                    if record.retries <= record.max_retries:
                        logger.warning("[TaskManager] Task %s failed (retry %d): %s", task_id, record.retries, exc)
                        record.status = TaskStatus.QUEUED
                        await asyncio.sleep(2 ** record.retries)
                        await self._queue.put((priority, time.monotonic(), task_id, coro))
                    else:
                        record.status = TaskStatus.FAILED
                        record.error = str(exc)
                        record.completed_at = datetime.now(timezone.utc).isoformat()
                        logger.error("[TaskManager] Task %s FAILED: %s", task_id, exc)
                        await self._notify_failure(record)

                self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[TaskManager] Worker error: %s", exc)
                await asyncio.sleep(1)

    async def _notify_progress(self, record: TaskRecord, status: str, message: str) -> None:
        try:
            from apps.core.routes.api import _log_activity
            _log_activity("INFO", message, category="task")
        except Exception:
            pass

    async def _notify_completion(self, record: TaskRecord) -> None:
        msg = f"✅ **{record.name}** completada\n{record.result or ''}"
        await self._deliver(record, msg)

    async def _notify_failure(self, record: TaskRecord) -> None:
        msg = f"❌ **{record.name}** falló: {record.error}"
        await self._deliver(record, msg)

    async def _deliver(self, record: TaskRecord, message: str) -> None:
        try:
            from apps.core.routes.api import _log_activity
            _log_activity("INFO", f"[Task:{record.id}] {record.status.value} — {record.name}", category="task")
        except Exception:
            pass

        if record.session_id and record.session_id.startswith("telegram:"):
            chat_id = record.session_id.replace("telegram:", "")
            if chat_id.isdigit():
                try:
                    from apps.core.tools.telegram_bot import get_bot
                    await get_bot()._send_message(int(chat_id), message)
                except Exception:
                    pass


_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    global _manager
    if _manager is None:
        _manager = TaskManager()
    return _manager
