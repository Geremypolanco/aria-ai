"""
ARIA Event Bus — Redis-backed, Kafka-compatible interface.

Design decisions:
- Uses RPUSH/LRANGE/LTRIM (Upstash REST-compatible) not XADD/XREAD
- Each topic is a Redis list key: "evtbus:{topic}"
- Dead-letter queue: "evtbus:dlq" for events that failed all retries
- Handler registry is in-memory per process; Redis is the durable backbone
- Correlation IDs flow through derive() on AriaEvent for causal tracing
- MAX_TOPIC_LENGTH caps memory growth; older events evicted (LTRIM)

The interface matches Kafka's producer/consumer model so the backend can
be swapped to native Kafka by replacing _publish_to_redis / _consume_from_redis
without changing any caller code.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from apps.core.events.schemas import AriaEvent, EventType

logger = logging.getLogger("aria.events.bus")

_TOPIC_PREFIX   = "evtbus:"
_DLQ_KEY        = "evtbus:dlq"
_MAX_TOPIC_LEN  = 10_000
_MAX_DLQ_LEN    = 1_000
_MAX_RETRIES    = 3

HandlerFn = Callable[[AriaEvent], Awaitable[None]]


class EventBus:
    """
    Central async event bus. Publish events to named topics; subscribe handlers
    that are called when events arrive. Supports:

    - publish(event, topic)           → durable to Redis + in-process fan-out
    - subscribe(event_type, handler)  → in-process handler registration
    - consume(topic, n)               → pull n events from Redis for replay
    - replay(topic, from_ts)          → re-deliver stored events to handlers
    - dead_letter_count()             → inspect DLQ size
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[HandlerFn]] = defaultdict(list)
        self._wildcard_handlers: list[HandlerFn] = []
        self._published: int = 0
        self._delivered: int = 0
        self._failed: int = 0

    def subscribe(self, event_type: EventType, handler: HandlerFn) -> None:
        self._handlers[event_type.value].append(handler)

    def subscribe_all(self, handler: HandlerFn) -> None:
        """Handler called for every event regardless of type."""
        self._wildcard_handlers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: HandlerFn) -> bool:
        key = event_type.value
        if handler in self._handlers[key]:
            self._handlers[key].remove(handler)
            return True
        return False

    async def publish(self, event: AriaEvent, topic: Optional[str] = None) -> None:
        topic = topic or event.event_type.value
        self._published += 1

        # Durable write first; if Redis is down, still fan-out in-process
        await self._persist(event, topic)
        await self._fan_out(event)

    async def publish_many(self, events: list[AriaEvent], topic: Optional[str] = None) -> None:
        for event in events:
            await self.publish(event, topic)

    async def consume(self, topic: str, n: int = 100, offset: int = 0) -> list[AriaEvent]:
        """Pull stored events from Redis for a topic (for replay or inspection)."""
        try:
            from apps.core.memory.redis_client import get_cache
            raw_list = await get_cache().get(f"{_TOPIC_PREFIX}{topic}")
            if not raw_list or not isinstance(raw_list, list):
                return []
            items = raw_list[offset: offset + n]
            events = []
            for item in items:
                try:
                    d = item if isinstance(item, dict) else json.loads(item)
                    events.append(AriaEvent.from_dict(d))
                except Exception:
                    pass
            return events
        except Exception as exc:
            logger.warning("[EventBus] consume failed: %s", exc)
            return []

    async def replay(self, topic: str, from_ts: float = 0.0, limit: int = 500) -> int:
        """Re-deliver stored events with ts >= from_ts to in-process handlers."""
        events = await self.consume(topic, n=limit)
        count = 0
        for event in events:
            if event.ts >= from_ts:
                await self._fan_out(event)
                count += 1
        return count

    async def dead_letter_count(self) -> int:
        try:
            from apps.core.memory.redis_client import get_cache
            raw = await get_cache().get(_DLQ_KEY)
            return len(raw) if isinstance(raw, list) else 0
        except Exception:
            return 0

    async def consume_dlq(self, n: int = 50) -> list[dict]:
        try:
            from apps.core.memory.redis_client import get_cache
            raw = await get_cache().get(_DLQ_KEY)
            if not raw or not isinstance(raw, list):
                return []
            return raw[:n]
        except Exception:
            return []

    def stats(self) -> dict:
        return {
            "published": self._published,
            "delivered": self._delivered,
            "failed": self._failed,
            "subscriptions": {k: len(v) for k, v in self._handlers.items() if v},
            "wildcard_handlers": len(self._wildcard_handlers),
        }

    # ── Private ──────────────────────────────────────────────────────────────

    async def _persist(self, event: AriaEvent, topic: str) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            key = f"{_TOPIC_PREFIX}{topic}"

            existing = await cache.get(key)
            items: list = existing if isinstance(existing, list) else []
            items.append(event.to_dict())

            # Evict oldest entries to cap growth
            if len(items) > _MAX_TOPIC_LEN:
                items = items[-_MAX_TOPIC_LEN:]

            await cache.set(key, items, ttl_seconds=60 * 60 * 24 * 7)
        except Exception as exc:
            logger.warning("[EventBus] persist failed for topic '%s': %s", topic, exc)

    async def _fan_out(self, event: AriaEvent) -> None:
        handlers = list(self._handlers.get(event.event_type.value, []))
        handlers.extend(self._wildcard_handlers)
        if not handlers:
            return

        for handler in handlers:
            for attempt in range(_MAX_RETRIES):
                try:
                    await handler(event)
                    self._delivered += 1
                    break
                except Exception as exc:
                    if attempt == _MAX_RETRIES - 1:
                        self._failed += 1
                        logger.error(
                            "[EventBus] handler %s failed after %d retries for %s: %s",
                            getattr(handler, "__name__", "?"), _MAX_RETRIES, event.event_type, exc,
                        )
                        await self._send_to_dlq(event, handler, str(exc))


    async def _send_to_dlq(self, event: AriaEvent, handler: HandlerFn, error: str) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            existing = await cache.get(_DLQ_KEY)
            items: list = existing if isinstance(existing, list) else []
            items.append({
                "event": event.to_dict(),
                "handler": getattr(handler, "__name__", "unknown"),
                "error": error,
                "dlq_at": datetime.now(timezone.utc).isoformat(),
            })
            if len(items) > _MAX_DLQ_LEN:
                items = items[-_MAX_DLQ_LEN:]
            await cache.set(_DLQ_KEY, items, ttl_seconds=60 * 60 * 24 * 30)
        except Exception:
            pass


_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
