"""
ARIA Temporal Memory — Time-ordered event log with causal chain tracking.

Temporal memory answers:
  "What happened at 3pm yesterday?" — point query
  "What changed in the last 24 hours?" — range query
  "Why did revenue spike on Tuesday?" — causal chain query
  "What was ARIA doing when the error occurred?" — context query

Each event has:
  - Timestamp (when it happened)
  - Type (what kind of event)
  - Entity (what entity was involved)
  - Payload (what happened in detail)
  - Causal links (what caused this event, what it caused)

This builds a causal timeline that enables:
  - Root cause analysis ("tool X failed because Y happened 3 minutes earlier")
  - Pattern detection ("income cycles fail every Tuesday — why?")
  - Longitudinal learning ("ARIA's response time is improving over weeks")
  - Replay (reconstruct what happened in any time window)
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("aria.memory.temporal")

EVENT_TTL = 86400 * 30   # 30 days
MAX_IN_MEMORY = 1000     # keep in process
CAUSAL_WINDOW_SECONDS = 300  # events within 5 min are potentially causal


class EventType(str, Enum):
    INCOME_CYCLE = "income_cycle"
    AI_CALL = "ai_call"
    TOOL_CALL = "tool_call"
    AGENT_RUN = "agent_run"
    GOAL_UPDATE = "goal_update"
    MEMORY_WRITE = "memory_write"
    USER_MESSAGE = "user_message"
    ARIA_RESPONSE = "aria_response"
    ERROR = "error"
    SYSTEM = "system"
    REFLECTION = "reflection"
    PLAN_UPDATE = "plan_update"


@dataclass
class TemporalEvent:
    id: str
    ts: float                        # UNIX timestamp (float for sub-second)
    ts_iso: str                      # ISO format for readability
    event_type: EventType
    entity_id: str                   # which entity this event concerns
    entity_name: str
    payload: dict[str, Any]
    caused_by: list[str]             # event IDs that caused this event
    caused: list[str]                # event IDs this event caused (populated later)
    tags: list[str]
    success: bool = True
    importance: float = 0.5         # 0.0–1.0; high-importance events are kept longer

    def to_dict(self) -> dict:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TemporalEvent":
        d = dict(d)
        d["event_type"] = EventType(d["event_type"])
        return cls(**d)

    @property
    def datetime(self) -> datetime:
        return datetime.fromtimestamp(self.ts, tz=timezone.utc)

    def age_seconds(self) -> float:
        return datetime.now(timezone.utc).timestamp() - self.ts


class TemporalMemory:
    """
    Ordered event log with causal chain tracking and time-range queries.

    Usage:
        mem = TemporalMemory()

        # Record events
        e1 = await mem.record(
            event_type=EventType.INCOME_CYCLE,
            entity_id="income_loop_1",
            entity_name="IncomeLoop",
            payload={"strategy": "content_pipeline", "revenue": 42.0},
            success=True,
        )

        # Query time ranges
        last_hour = await mem.since(minutes=60)
        today = await mem.range(start=datetime.today().replace(hour=0))

        # Causal analysis
        causes = await mem.causal_chain(e1.id, direction="backward")
    """

    def __init__(self) -> None:
        self._events: list[TemporalEvent] = []  # sorted by ts ascending
        self._index: dict[str, TemporalEvent] = {}  # id → event

    # ── Recording ────────────────────────────────────────────────────────

    async def record(
        self,
        event_type: EventType,
        entity_id: str,
        entity_name: str,
        payload: dict[str, Any],
        success: bool = True,
        tags: list[str] | None = None,
        importance: float = 0.5,
        caused_by: list[str] | None = None,
    ) -> TemporalEvent:
        now = datetime.now(timezone.utc)
        event_id = uuid.uuid4().hex[:10]

        # Auto-detect causal predecessors within the causal window
        auto_causes = caused_by or []
        if not auto_causes:
            cutoff = now.timestamp() - CAUSAL_WINDOW_SECONDS
            auto_causes = [
                e.id for e in self._events[-20:]  # only check recent events
                if e.ts >= cutoff and e.entity_id == entity_id
            ]

        event = TemporalEvent(
            id=event_id,
            ts=now.timestamp(),
            ts_iso=now.isoformat(),
            event_type=event_type,
            entity_id=entity_id,
            entity_name=entity_name,
            payload=payload,
            caused_by=auto_causes,
            caused=[],
            tags=tags or [],
            success=success,
            importance=importance,
        )

        # Update caused[] on predecessors
        for pred_id in auto_causes:
            pred = self._index.get(pred_id)
            if pred and event_id not in pred.caused:
                pred.caused.append(event_id)

        self._events.append(event)
        self._index[event_id] = event

        # Evict oldest low-importance events if over limit
        if len(self._events) > MAX_IN_MEMORY:
            self._evict()

        await self._persist(event)
        return event

    # ── Queries ───────────────────────────────────────────────────────────

    async def since(
        self,
        minutes: float | None = None,
        hours: float | None = None,
        days: float | None = None,
        event_type: EventType | None = None,
    ) -> list[TemporalEvent]:
        total_seconds = 0
        if minutes:
            total_seconds += minutes * 60
        if hours:
            total_seconds += hours * 3600
        if days:
            total_seconds += days * 86400
        if total_seconds == 0:
            total_seconds = 3600  # default 1h

        cutoff = datetime.now(timezone.utc).timestamp() - total_seconds
        return self._filter(ts_from=cutoff, event_type=event_type)

    async def range(
        self,
        start: datetime,
        end: datetime | None = None,
        event_type: EventType | None = None,
    ) -> list[TemporalEvent]:
        end = end or datetime.now(timezone.utc)
        return self._filter(
            ts_from=start.timestamp(),
            ts_to=end.timestamp(),
            event_type=event_type,
        )

    async def get_event(self, event_id: str) -> Optional[TemporalEvent]:
        return self._index.get(event_id)

    async def recent(self, n: int = 20, event_type: EventType | None = None) -> list[TemporalEvent]:
        events = self._events[-n * 3:]  # over-fetch then filter
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-n:]

    async def failures(self, hours: float = 24) -> list[TemporalEvent]:
        cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
        return [e for e in self._events if e.ts >= cutoff and not e.success]

    # ── Causal Analysis ───────────────────────────────────────────────────

    async def causal_chain(
        self, event_id: str, direction: str = "backward", max_depth: int = 5
    ) -> list[TemporalEvent]:
        """
        Trace the causal chain from an event.
        direction="backward" → what caused this event (root cause analysis)
        direction="forward"  → what this event caused (impact analysis)
        """
        result = []
        visited = set()
        queue = [event_id]
        depth = 0

        while queue and depth < max_depth:
            current_ids = queue[:]
            queue = []
            for eid in current_ids:
                if eid in visited:
                    continue
                visited.add(eid)
                ev = self._index.get(eid)
                if not ev:
                    continue
                result.append(ev)
                if direction == "backward":
                    queue.extend(ev.caused_by)
                else:
                    queue.extend(ev.caused)
            depth += 1

        return result

    async def pattern_frequency(
        self, event_type: EventType, window_hours: float = 168
    ) -> dict:
        """Count event frequency by hour-of-day to detect patterns."""
        events = await self.since(hours=window_hours, event_type=event_type)
        by_hour: dict[int, int] = {}
        for ev in events:
            hour = ev.datetime.hour
            by_hour[hour] = by_hour.get(hour, 0) + 1
        peak_hour = max(by_hour, key=by_hour.get) if by_hour else None
        return {
            "event_type": event_type.value,
            "window_hours": window_hours,
            "total_events": len(events),
            "by_hour": by_hour,
            "peak_hour": peak_hour,
            "success_rate": (
                sum(1 for e in events if e.success) / len(events) if events else 0.0
            ),
        }

    def summary(self) -> dict:
        if not self._events:
            return {"total_events": 0}
        types: dict[str, int] = {}
        for ev in self._events:
            types[ev.event_type.value] = types.get(ev.event_type.value, 0) + 1
        oldest = datetime.fromtimestamp(self._events[0].ts, tz=timezone.utc).isoformat()
        newest = datetime.fromtimestamp(self._events[-1].ts, tz=timezone.utc).isoformat()
        return {
            "total_events": len(self._events),
            "by_type": types,
            "failure_count": sum(1 for e in self._events if not e.success),
            "oldest": oldest,
            "newest": newest,
        }

    # ── Eviction ─────────────────────────────────────────────────────────

    def _evict(self) -> None:
        """Remove 10% of oldest, lowest-importance events."""
        evict_count = len(self._events) // 10
        sorted_by_keep = sorted(
            self._events,
            key=lambda e: (e.ts * e.importance),  # old + low importance = evict first
        )
        to_evict = {e.id for e in sorted_by_keep[:evict_count]}
        self._events = [e for e in self._events if e.id not in to_evict]
        for eid in to_evict:
            self._index.pop(eid, None)

    def _filter(
        self,
        ts_from: float = 0,
        ts_to: float | None = None,
        event_type: EventType | None = None,
    ) -> list[TemporalEvent]:
        ts_to = ts_to or datetime.now(timezone.utc).timestamp() + 1
        return [
            e for e in self._events
            if ts_from <= e.ts <= ts_to
            and (event_type is None or e.event_type == event_type)
        ]

    # ── Persistence ───────────────────────────────────────────────────────

    async def _persist(self, event: TemporalEvent) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if cache:
                await cache.set(
                    f"aria:temporal:{event.id}",
                    json.dumps(event.to_dict()),
                    ttl_seconds=EVENT_TTL,
                )
                await cache.rpush("aria:temporal:index", event.id)
        except Exception as exc:
            logger.debug("[TemporalMem] Persist failed: %s", exc)


_memory: Optional[TemporalMemory] = None


def get_temporal_memory() -> TemporalMemory:
    global _memory
    if _memory is None:
        _memory = TemporalMemory()
    return _memory
