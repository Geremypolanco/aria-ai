from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from apps.core.memory.redis_client import get_cache

_TTL = 365 * 24 * 3600
_CACHE_KEY = "business:operations:v1"


@dataclass
class OperationalMetric:
    metric_id: str
    name: str
    value: float
    target: float
    unit: str
    category: str
    timestamp: float
    trend: str = "stable"

    def to_dict(self) -> dict:
        return {
            "metric_id": self.metric_id,
            "name": self.name,
            "value": self.value,
            "target": self.target,
            "unit": self.unit,
            "category": self.category,
            "timestamp": self.timestamp,
            "trend": self.trend,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OperationalMetric:
        return cls(
            metric_id=data["metric_id"],
            name=data["name"],
            value=data["value"],
            target=data["target"],
            unit=data.get("unit", ""),
            category=data.get("category", "general"),
            timestamp=data.get("timestamp", time.time()),
            trend=data.get("trend", "stable"),
        )


class OperationsManager:
    def __init__(self) -> None:
        self._metrics: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._metrics = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        self._loaded = True
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._metrics, ttl_seconds=_TTL)
        except Exception:
            pass

    def _detect_trend(self, name: str, new_value: float) -> str:
        prev = None
        for m in reversed(self._metrics):
            if m.get("name") == name:
                prev = m.get("value")
                break
        if prev is None:
            return "stable"
        if new_value > prev * 1.02:
            return "up"
        if new_value < prev * 0.98:
            return "down"
        return "stable"

    async def record_metric(
        self,
        name: str,
        value: float,
        target: float,
        unit: str,
        category: str,
    ) -> OperationalMetric:
        await self._load()
        trend = self._detect_trend(name, value)
        metric = OperationalMetric(
            metric_id=str(uuid.uuid4()),
            name=name,
            value=value,
            target=target,
            unit=unit,
            category=category,
            timestamp=time.time(),
            trend=trend,
        )
        self._metrics.append(metric.to_dict())
        if len(self._metrics) > 5000:
            self._metrics = self._metrics[-5000:]
        await self._save()
        return metric

    async def kpi_dashboard(self) -> dict:
        await self._load()
        # Use latest value per metric name
        latest: dict[str, dict] = {}
        for m in self._metrics:
            latest[m["name"]] = m
        grouped: dict[str, list[dict]] = {}
        for m in latest.values():
            cat = m.get("category", "general")
            grouped.setdefault(cat, []).append(m)
        dashboard: dict[str, list[dict]] = {}
        for cat, metrics in grouped.items():
            cat_items: list[dict] = []
            for m in metrics:
                value = m["value"]
                target = max(m["target"], 0.01)
                gap_pct = round((target - value) / target * 100, 2)
                ratio = value / target
                if ratio >= 0.9:
                    status = "on_track"
                elif ratio >= 0.7:
                    status = "at_risk"
                else:
                    status = "off_track"
                cat_items.append(
                    {
                        "name": m["name"],
                        "current": value,
                        "target": m["target"],
                        "gap_pct": gap_pct,
                        "status": status,
                        "unit": m.get("unit", ""),
                        "trend": m.get("trend", "stable"),
                    }
                )
            dashboard[cat] = cat_items
        return dashboard

    async def operational_health(self) -> dict:
        await self._load()
        latest: dict[str, dict] = {}
        for m in self._metrics:
            latest[m["name"]] = m
        if not latest:
            return {
                "overall_health_score": 1.0,
                "metrics_on_track": 0,
                "metrics_at_risk": 0,
                "metrics_off_track": 0,
                "critical_issues": [],
            }
        on_track = 0
        at_risk = 0
        off_track = 0
        critical_issues: list[str] = []
        for m in latest.values():
            target = max(m["target"], 0.01)
            ratio = m["value"] / target
            if ratio >= 0.9:
                on_track += 1
            elif ratio >= 0.7:
                at_risk += 1
            else:
                off_track += 1
                critical_issues.append(
                    f"{m['name']}: {m['value']} {m.get('unit','')} vs target {m['target']} (gap: {(1-ratio)*100:.0f}%)"
                )
        total = len(latest)
        health_score = round(on_track / total, 3) if total else 1.0
        return {
            "overall_health_score": health_score,
            "metrics_on_track": on_track,
            "metrics_at_risk": at_risk,
            "metrics_off_track": off_track,
            "critical_issues": critical_issues[:5],
        }

    async def optimization_opportunities(self) -> list[dict]:
        await self._load()
        latest: dict[str, dict] = {}
        for m in self._metrics:
            latest[m["name"]] = m
        opportunities: list[dict] = []
        for m in latest.values():
            target = max(m["target"], 0.01)
            ratio = m["value"] / target
            if ratio < 0.7:
                gap = m["target"] - m["value"]
                estimated_impact = round(gap * 0.5, 2)
                opportunities.append(
                    {
                        "metric": m["name"],
                        "current": m["value"],
                        "target": m["target"],
                        "unit": m.get("unit", ""),
                        "gap": round(gap, 2),
                        "gap_pct": round((1 - ratio) * 100, 1),
                        "estimated_impact": estimated_impact,
                        "recommendation": f"Improve {m['name']} by {round((1 - ratio) * 100, 0):.0f}% to reach target",
                    }
                )
        opportunities.sort(key=lambda o: -o["gap_pct"])
        return opportunities

    def summary(self) -> dict:
        if not self._metrics:
            return {"total_metrics": 0, "health_score": 1.0}
        latest: dict[str, dict] = {}
        for m in self._metrics:
            latest[m["name"]] = m
        on_track = sum(1 for m in latest.values() if m["value"] / max(m["target"], 0.01) >= 0.9)
        health_score = round(on_track / len(latest), 3) if latest else 1.0
        return {
            "total_metrics": len(latest),
            "health_score": health_score,
        }


_operations_manager_instance: OperationsManager | None = None


def get_operations_manager() -> OperationsManager:
    global _operations_manager_instance
    if _operations_manager_instance is None:
        _operations_manager_instance = OperationsManager()
    return _operations_manager_instance
