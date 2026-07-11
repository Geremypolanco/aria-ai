"""
log_bus.py — Live agent logs over Pub/Sub (not the persistent DB).

Workers `publish()` each log line to a lightweight Redis Pub/Sub channel keyed by
task id. The web server's WebSocket endpoint `subscribe()`s to that channel and
streams lines to the browser — so live logs cost near-zero CPU/memory and never
touch the durable store.

Redis Pub/Sub when `REDIS_URL` is set; an in-process fan-out (asyncio.Queue per
subscriber) otherwise, so it works single-container and in tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import defaultdict
from collections.abc import AsyncIterator

logger = logging.getLogger("aria.log_bus")


def channel_for(task_id: str) -> str:
    return f"aria:logs:{task_id}"


# ── in-process fan-out ────────────────────────────────────────────
_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)


async def _get_redis():
    from apps.core.scale.task_queue import _get_redis as _r

    return await _r()


async def publish(task_id: str, message: str, *, level: str = "info") -> None:
    """Publish one log line to a task's channel."""
    payload = json.dumps({"ts": time.time(), "level": level, "msg": message})
    ch = channel_for(task_id)
    r = await _get_redis()
    if r is not None:
        with contextlib.suppress(Exception):
            await r.publish(ch, payload)
        return
    for q in list(_subscribers.get(ch, ())):
        with contextlib.suppress(Exception):
            q.put_nowait(payload)


async def subscribe(task_id: str) -> AsyncIterator[str]:
    """Yield JSON log lines for a task until the consumer stops."""
    ch = channel_for(task_id)
    r = await _get_redis()
    if r is not None:
        pubsub = r.pubsub()
        await pubsub.subscribe(ch)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    yield msg["data"]
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(ch)
                await pubsub.close()
        return

    q: asyncio.Queue = asyncio.Queue()
    _subscribers[ch].add(q)
    try:
        while True:
            yield await q.get()
    finally:
        _subscribers[ch].discard(q)
        if not _subscribers[ch]:
            _subscribers.pop(ch, None)
