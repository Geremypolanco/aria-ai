from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from apps.core.memory.redis_client import get_cache

_TTL = 365 * 24 * 3600
_CACHE_KEY = "business:executive:v1"

_DEFAULT_METRICS: dict = {
    "revenue_usd": 0.0,
    "revenue_growth_pct": 0.0,
    "customer_count": 0,
    "customer_growth_pct": 0.0,
    "avg_order_value": 0.0,
    "conversion_rate": 0.02,
    "churn_rate": 0.05,
    "net_profit_usd": 0.0,
    "top_channels": [],
}


@dataclass
class BusinessSnapshot:
    snapshot_id: str
    period: str
    revenue_usd: float
    revenue_growth_pct: float
    customer_count: int
    customer_growth_pct: float
    avg_order_value: float
    conversion_rate: float
    churn_rate: float
    net_profit_usd: float
    top_channels: list[str]
    alerts: list[str]
    generated_at: float

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "period": self.period,
            "revenue_usd": self.revenue_usd,
            "revenue_growth_pct": self.revenue_growth_pct,
            "customer_count": self.customer_count,
            "customer_growth_pct": self.customer_growth_pct,
            "avg_order_value": self.avg_order_value,
            "conversion_rate": self.conversion_rate,
            "churn_rate": self.churn_rate,
            "net_profit_usd": self.net_profit_usd,
            "top_channels": self.top_channels,
            "alerts": self.alerts,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BusinessSnapshot:
        return cls(
            snapshot_id=data["snapshot_id"],
            period=data["period"],
            revenue_usd=data.get("revenue_usd", 0.0),
            revenue_growth_pct=data.get("revenue_growth_pct", 0.0),
            customer_count=data.get("customer_count", 0),
            customer_growth_pct=data.get("customer_growth_pct", 0.0),
            avg_order_value=data.get("avg_order_value", 0.0),
            conversion_rate=data.get("conversion_rate", 0.0),
            churn_rate=data.get("churn_rate", 0.0),
            net_profit_usd=data.get("net_profit_usd", 0.0),
            top_channels=data.get("top_channels", []),
            alerts=data.get("alerts", []),
            generated_at=data.get("generated_at", time.time()),
        )


def _detect_alerts(
    revenue_growth_pct: float,
    churn_rate: float,
    conversion_rate: float,
) -> list[str]:
    alerts: list[str] = []
    if revenue_growth_pct < 0:
        alerts.append("Revenue declining")
    if churn_rate > 0.1:
        alerts.append("High churn detected")
    if conversion_rate < 0.01:
        alerts.append("Low conversion alert")
    return alerts


class ExecutiveDashboard:
    def __init__(self) -> None:
        self._snapshots: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._snapshots = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        self._loaded = True
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._snapshots[-200:], ttl_seconds=_TTL)
        except Exception:
            pass

    async def generate_snapshot(
        self,
        period: str = "weekly",
        metrics: dict | None = None,
    ) -> BusinessSnapshot:
        await self._load()
        m = {**_DEFAULT_METRICS, **(metrics or {})}
        revenue_usd = float(m.get("revenue_usd", 0.0))
        revenue_growth_pct = float(m.get("revenue_growth_pct", 0.0))
        customer_count = int(m.get("customer_count", 0))
        customer_growth_pct = float(m.get("customer_growth_pct", 0.0))
        avg_order_value = float(m.get("avg_order_value", 0.0))
        conversion_rate = float(m.get("conversion_rate", 0.02))
        churn_rate = float(m.get("churn_rate", 0.05))
        net_profit_usd = float(m.get("net_profit_usd", revenue_usd * 0.3))
        top_channels = list(m.get("top_channels", []))
        alerts = _detect_alerts(revenue_growth_pct, churn_rate, conversion_rate)
        snapshot = BusinessSnapshot(
            snapshot_id=str(uuid.uuid4()),
            period=period,
            revenue_usd=revenue_usd,
            revenue_growth_pct=revenue_growth_pct,
            customer_count=customer_count,
            customer_growth_pct=customer_growth_pct,
            avg_order_value=avg_order_value,
            conversion_rate=conversion_rate,
            churn_rate=churn_rate,
            net_profit_usd=net_profit_usd,
            top_channels=top_channels,
            alerts=alerts,
            generated_at=time.time(),
        )
        self._snapshots.append(snapshot.to_dict())
        await self._save()
        return snapshot

    async def weekly_report(self) -> dict:
        snapshot = await self.generate_snapshot(period="weekly")
        recommendations: list[str] = []
        if snapshot.revenue_growth_pct < 0:
            recommendations.append("Investigate root cause of revenue decline immediately")
        elif snapshot.revenue_growth_pct > 10:
            recommendations.append("Scale successful channels with increased budget")
        if snapshot.churn_rate > 0.05:
            recommendations.append("Launch customer retention campaign to reduce churn")
        if snapshot.conversion_rate < 0.02:
            recommendations.append("A/B test landing pages and pricing to improve conversion")
        if not recommendations:
            recommendations.append("Maintain current trajectory and monitor KPIs weekly")
        return {
            "period": "weekly",
            "snapshot": snapshot.to_dict(),
            "recommendations": recommendations,
            "alerts": snapshot.alerts,
            "health": (
                "critical"
                if len(snapshot.alerts) >= 2
                else "at_risk" if snapshot.alerts else "healthy"
            ),
        }

    async def compare_periods(self, period1: str, period2: str) -> dict:
        await self._load()
        snap1 = next(
            (
                BusinessSnapshot.from_dict(s)
                for s in reversed(self._snapshots)
                if s["period"] == period1
            ),
            None,
        )
        snap2 = next(
            (
                BusinessSnapshot.from_dict(s)
                for s in reversed(self._snapshots)
                if s["period"] == period2
            ),
            None,
        )
        if not snap1 or not snap2:
            return {
                "error": f"Could not find snapshots for both periods: {period1}, {period2}",
                "available_periods": list({s["period"] for s in self._snapshots}),
            }
        return {
            "period1": period1,
            "period2": period2,
            "revenue_delta_usd": round(snap1.revenue_usd - snap2.revenue_usd, 2),
            "revenue_growth_delta_pct": round(
                snap1.revenue_growth_pct - snap2.revenue_growth_pct, 2
            ),
            "customer_delta": snap1.customer_count - snap2.customer_count,
            "conversion_rate_delta": round(snap1.conversion_rate - snap2.conversion_rate, 4),
            "churn_delta": round(snap1.churn_rate - snap2.churn_rate, 4),
            "net_profit_delta_usd": round(snap1.net_profit_usd - snap2.net_profit_usd, 2),
        }

    async def strategic_alerts(self) -> list[str]:
        await self._load()
        all_alerts: list[str] = []
        for s in self._snapshots[-20:]:
            all_alerts.extend(s.get("alerts", []))
        # Deduplicate preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for a in all_alerts:
            if a not in seen:
                seen.add(a)
                unique.append(a)
        return unique

    async def board_summary(self) -> dict:
        await self._load()
        if not self._snapshots:
            return {
                "status": "No data yet — generate first snapshot to see summary",
                "revenue_usd": 0.0,
                "customer_count": 0,
                "alerts": [],
                "health": "unknown",
            }
        latest = BusinessSnapshot.from_dict(self._snapshots[-1])
        return {
            "period": latest.period,
            "revenue_usd": latest.revenue_usd,
            "revenue_growth_pct": latest.revenue_growth_pct,
            "net_profit_usd": latest.net_profit_usd,
            "customer_count": latest.customer_count,
            "top_channels": latest.top_channels,
            "alerts": latest.alerts,
            "churn_rate": latest.churn_rate,
            "conversion_rate": latest.conversion_rate,
            "health": (
                "critical" if len(latest.alerts) >= 2 else "at_risk" if latest.alerts else "healthy"
            ),
            "generated_at": latest.generated_at,
        }

    def summary(self) -> dict:
        if not self._snapshots:
            return {"total_snapshots": 0, "latest_revenue_usd": 0.0}
        latest = self._snapshots[-1]
        return {
            "total_snapshots": len(self._snapshots),
            "latest_revenue_usd": latest.get("revenue_usd", 0.0),
        }


_executive_dashboard_instance: ExecutiveDashboard | None = None


def get_executive_dashboard() -> ExecutiveDashboard:
    global _executive_dashboard_instance
    if _executive_dashboard_instance is None:
        _executive_dashboard_instance = ExecutiveDashboard()
    return _executive_dashboard_instance
