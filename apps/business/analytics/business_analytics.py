from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import dataclass

from apps.core.memory.redis_client import get_cache

_TTL = 90 * 24 * 3600
_CACHE_KEY = "business:analytics:v1"
_MAX_EVENTS = 10000


@dataclass
class AnalyticsEvent:
    event_id: str
    event_type: str
    properties: dict
    timestamp: float
    session_id: str
    user_id: str

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "properties": self.properties,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AnalyticsEvent:
        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            properties=data.get("properties", {}),
            timestamp=data.get("timestamp", time.time()),
            session_id=data.get("session_id", ""),
            user_id=data.get("user_id", ""),
        )


class BusinessAnalytics:
    def __init__(self) -> None:
        self._events: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._events = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        self._loaded = True
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._events[-_MAX_EVENTS:], ttl_seconds=_TTL)
        except Exception:
            pass

    async def track(
        self,
        event_type: str,
        properties: dict | None = None,
        user_id: str = "",
        session_id: str = "",
    ) -> AnalyticsEvent:
        await self._load()
        event = AnalyticsEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            properties=properties or {},
            timestamp=time.time(),
            session_id=session_id,
            user_id=user_id,
        )
        self._events.append(event.to_dict())
        if len(self._events) > _MAX_EVENTS:
            self._events = self._events[-_MAX_EVENTS:]
        await self._save()
        return event

    async def funnel(self, steps: list[str]) -> list[dict]:
        await self._load()
        if not steps:
            return []
        step_counts: list[int] = []
        for step in steps:
            count = sum(1 for e in self._events if e["event_type"] == step)
            step_counts.append(count)
        result: list[dict] = []
        for i, step in enumerate(steps):
            count = step_counts[i]
            if i == 0:
                cvr = 1.0
                drop_rate = 0.0
            else:
                prev = step_counts[i - 1]
                cvr = round(count / max(prev, 1), 4)
                drop_rate = round(1.0 - cvr, 4)
            result.append(
                {
                    "step": step,
                    "count": count,
                    "cvr": cvr,
                    "drop_rate": drop_rate,
                }
            )
        return result

    async def cohort_retention(self, cohort_start_ts: float, periods: int = 4) -> dict:
        await self._load()
        period_length = 7 * 86400  # weekly periods
        cohort_users: set[str] = set()
        for e in self._events:
            if cohort_start_ts <= e["timestamp"] < cohort_start_ts + period_length:
                uid = e.get("user_id", "")
                if uid:
                    cohort_users.add(uid)
        if not cohort_users:
            return {
                "cohort_size": 0,
                "periods": [{"period": i, "retention_rate": 0.0} for i in range(periods)],
            }
        retention_periods: list[dict] = []
        for period_i in range(periods):
            period_start = cohort_start_ts + period_i * period_length
            period_end = period_start + period_length
            active_in_period: set[str] = set()
            for e in self._events:
                if period_start <= e["timestamp"] < period_end:
                    uid = e.get("user_id", "")
                    if uid in cohort_users:
                        active_in_period.add(uid)
            retention_rate = round(len(active_in_period) / len(cohort_users), 4)
            retention_periods.append(
                {
                    "period": period_i,
                    "retention_rate": retention_rate,
                }
            )
        return {
            "cohort_size": len(cohort_users),
            "periods": retention_periods,
        }

    async def top_events(self, limit: int = 10) -> list[dict]:
        await self._load()
        if not self._events:
            return []
        counter = Counter(e["event_type"] for e in self._events)
        total = len(self._events)
        result: list[dict] = []
        for event_type, count in counter.most_common(limit):
            result.append(
                {
                    "event_type": event_type,
                    "count": count,
                    "percentage": round(count / total * 100, 2),
                }
            )
        return result

    async def revenue_attribution_by_event(self, revenue_event: str = "purchase") -> dict:
        await self._load()
        by_source: dict[str, float] = {}
        for e in self._events:
            if e["event_type"] == revenue_event:
                props = e.get("properties", {})
                source = props.get("source", props.get("channel", "direct"))
                amount = float(props.get("amount", props.get("revenue", 0.0)))
                by_source[source] = by_source.get(source, 0.0) + amount
        total = sum(by_source.values())
        return {
            "total_revenue_usd": round(total, 2),
            "by_source": {
                source: {
                    "revenue_usd": round(amount, 2),
                    "share_pct": round(amount / max(total, 0.01) * 100, 2),
                }
                for source, amount in sorted(by_source.items(), key=lambda x: -x[1])
            },
        }

    async def diagnostics(self) -> dict:
        await self._load()
        total = len(self._events)
        unique_users: set[str] = set()
        event_types: set[str] = set()
        for e in self._events:
            uid = e.get("user_id", "")
            if uid:
                unique_users.add(uid)
            event_types.add(e["event_type"])
        if total == 0:
            health = "empty"
        elif total < 50:
            health = "sparse"
        else:
            health = "good"
        return {
            "total_events": total,
            "unique_users": len(unique_users),
            "event_types": len(event_types),
            "data_health": health,
        }

    def summary(self) -> dict:
        unique_users: set[str] = set()
        for e in self._events:
            uid = e.get("user_id", "")
            if uid:
                unique_users.add(uid)
        return {
            "total_events": len(self._events),
            "unique_users": len(unique_users),
        }


_business_analytics_instance: BusinessAnalytics | None = None


def get_business_analytics() -> BusinessAnalytics:
    global _business_analytics_instance
    if _business_analytics_instance is None:
        _business_analytics_instance = BusinessAnalytics()
    return _business_analytics_instance
