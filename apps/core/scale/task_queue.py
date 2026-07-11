"""
task_queue.py — Event-driven mission queue (producer / consumer).

The web endpoint is a *producer*: it validates the payload, enqueues a mission
with a unique id, and returns immediately (HTTP 202). Stateless *workers* are
*consumers*: they pop missions and run them.

Backend: Redis (list `LPUSH`/`BRPOP` + a per-task status hash) when `REDIS_URL`
is configured; otherwise an in-process `asyncio.Queue` (single-container dev /
tests). Task state transitions are stored in the cache: queued → processing →
completed | failed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import Any

logger = logging.getLogger("aria.task_queue")

PENDING_KEY = "aria:mq:pending"
STATUS_KEY = "aria:mq:status:{tid}"
RESULT_TTL = 60 * 60 * 24  # keep results 24h

VALID_STATES = ("queued", "processing", "completed", "failed")


def new_task_id() -> str:
    return "task_" + secrets.token_urlsafe(12)


# ── Redis backend (lazy, optional) ────────────────────────────────
_redis: Any = None
_redis_checked = False


async def _get_redis() -> Any:
    """Return a redis.asyncio client if REDIS_URL is set + redis is installed."""
    global _redis, _redis_checked
    if _redis_checked:
        return _redis
    _redis_checked = True
    try:
        from apps.core.config import settings

        url = getattr(settings, "REDIS_URL", None)
        if not url:
            return None
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
        await _redis.ping()
        logger.info("[queue] Redis backend active")
    except Exception as exc:  # noqa: BLE001
        logger.info("[queue] no Redis (%s) — using in-process queue", exc)
        _redis = None
    return _redis


# ── in-process fallback ───────────────────────────────────────────
# A plain deque (loop-agnostic) polled by dequeue(), so it works across the
# separate event loops pytest creates per test.
from collections import deque  # noqa: E402

_mem_pending: deque[str] = deque()
_mem_status: dict[str, dict] = {}


class MissionQueue:
    """Redis-or-memory backed FIFO mission queue with status tracking."""

    async def enqueue(self, payload: dict, *, user_email: str = "") -> str:
        tid = new_task_id()
        status = {
            "id": tid,
            "state": "queued",
            "user_email": user_email,
            "payload": payload,
            "created_at": time.time(),
        }
        r = await _get_redis()
        if r is not None:
            await r.set(STATUS_KEY.format(tid=tid), json.dumps(status), ex=RESULT_TTL)
            await r.lpush(PENDING_KEY, tid)
        else:
            _mem_status[tid] = status
            _mem_pending.appendleft(tid)
        logger.info("[queue] enqueued %s (user=%s)", tid, user_email or "-")
        return tid

    async def dequeue(self, *, timeout: float = 5.0) -> dict | None:
        """Block up to `timeout` seconds for the next task; None on timeout."""
        r = await _get_redis()
        if r is not None:
            popped = await r.brpop(PENDING_KEY, timeout=int(timeout))
            if not popped:
                return None
            tid = popped[1]
            return await self.get_status(tid)
        # In-memory: poll the deque (FIFO — appendleft on enqueue, pop from right).
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _mem_pending:
                tid = _mem_pending.pop()
                return _mem_status.get(tid)
            await asyncio.sleep(0.02)
        return None

    async def set_status(self, tid: str, state: str, **fields: Any) -> None:
        if state not in VALID_STATES:
            raise ValueError(f"invalid state: {state}")
        r = await _get_redis()
        if r is not None:
            raw = await r.get(STATUS_KEY.format(tid=tid))
            data = json.loads(raw) if raw else {"id": tid}
            data.update(state=state, updated_at=time.time(), **fields)
            await r.set(STATUS_KEY.format(tid=tid), json.dumps(data), ex=RESULT_TTL)
        else:
            data = _mem_status.setdefault(tid, {"id": tid})
            data.update(state=state, updated_at=time.time(), **fields)

    async def get_status(self, tid: str) -> dict | None:
        r = await _get_redis()
        if r is not None:
            raw = await r.get(STATUS_KEY.format(tid=tid))
            return json.loads(raw) if raw else None
        return _mem_status.get(tid)

    async def depth(self) -> int:
        r = await _get_redis()
        if r is not None:
            return int(await r.llen(PENDING_KEY))
        return len(_mem_pending)


_queue: MissionQueue | None = None


def get_queue() -> MissionQueue:
    global _queue
    if _queue is None:
        _queue = MissionQueue()
    return _queue
