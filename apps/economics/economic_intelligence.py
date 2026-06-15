"""
ARIA Economic Intelligence Layer — tracks all economic activity across departments.
Monitors revenue, costs, ROI, and business metrics in real-time.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_ECONOMICS_KEY = "economics:intelligence:v1"
_ECONOMICS_TTL = 86400 * 90  # 90 days


@dataclass
class EconomicEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    event_type: str = ""   # "revenue", "cost", "investment", "conversion", "lead"
    source: str = ""       # department or system that generated it
    amount_usd: float = 0.0
    currency: str = "USD"
    metric: str = ""       # "revenue", "cac", "ltv", "roas", "cvr", "aov"
    value: float = 0.0
    context: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "amount_usd": round(self.amount_usd, 4),
            "currency": self.currency,
            "metric": self.metric,
            "value": round(self.value, 4),
            "context": self.context,
            "ts": self.ts,
        }


@dataclass
class EconomicSnapshot:
    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    period: str = "7d"
    total_revenue: float = 0.0
    total_costs: float = 0.0
    gross_profit: float = 0.0
    profit_margin_pct: float = 0.0
    avg_cac: float = 0.0
    avg_ltv: float = 0.0
    ltv_cac_ratio: float = 0.0
    avg_roas: float = 0.0
    avg_cvr: float = 0.0
    computational_cost_usd: float = 0.0   # AI API costs
    efficiency_score: float = 0.0         # revenue / total_cost ratio
    top_revenue_source: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "period": self.period,
            "total_revenue": round(self.total_revenue, 4),
            "total_costs": round(self.total_costs, 4),
            "gross_profit": round(self.gross_profit, 4),
            "profit_margin_pct": round(self.profit_margin_pct, 4),
            "avg_cac": round(self.avg_cac, 4),
            "avg_ltv": round(self.avg_ltv, 4),
            "ltv_cac_ratio": round(self.ltv_cac_ratio, 4),
            "avg_roas": round(self.avg_roas, 4),
            "avg_cvr": round(self.avg_cvr, 4),
            "computational_cost_usd": round(self.computational_cost_usd, 4),
            "efficiency_score": round(self.efficiency_score, 4),
            "top_revenue_source": self.top_revenue_source,
            "created_at": self.created_at,
        }


class EconomicIntelligence:
    """Tracks all economic activity across ARIA's departments."""

    def __init__(self) -> None:
        self._events: list[dict] = []
        self._snapshots: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_ECONOMICS_KEY)
                if data and isinstance(data, dict):
                    self._events = data.get("events", [])
                    self._snapshots = data.get("snapshots", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _ECONOMICS_KEY,
                {"events": self._events, "snapshots": self._snapshots},
                ttl_seconds=_ECONOMICS_TTL,
            )
        except Exception:
            pass

    async def record_event(
        self,
        event_type: str,
        source: str,
        amount_usd: float = 0.0,
        metric: str = "",
        value: float = 0.0,
        context: dict = {},
    ) -> EconomicEvent:
        await self._load()
        event = EconomicEvent(
            event_type=event_type,
            source=source,
            amount_usd=amount_usd,
            metric=metric,
            value=value,
            context=dict(context),
        )
        self._events.append(event.to_dict())
        await self._save()
        return event

    async def record_revenue(
        self, source: str, amount_usd: float, context: dict = {}
    ) -> EconomicEvent:
        return await self.record_event(
            event_type="revenue",
            source=source,
            amount_usd=amount_usd,
            metric="revenue",
            value=amount_usd,
            context=dict(context),
        )

    async def record_cost(
        self, source: str, amount_usd: float, cost_type: str = "operational"
    ) -> EconomicEvent:
        return await self.record_event(
            event_type="cost",
            source=source,
            amount_usd=amount_usd,
            metric="cost",
            value=amount_usd,
            context={"cost_type": cost_type},
        )

    async def record_conversion(
        self, source: str, revenue: float, cost: float
    ) -> EconomicEvent:
        roas = revenue / max(cost, 0.01)
        return await self.record_event(
            event_type="conversion",
            source=source,
            amount_usd=revenue,
            metric="roas",
            value=roas,
            context={"revenue": revenue, "cost": cost, "roas": round(roas, 4)},
        )

    async def snapshot(self, period: str = "7d") -> EconomicSnapshot:
        await self._load()

        # Determine cutoff time
        period_map = {"1d": 86400, "7d": 604800, "30d": 2592000, "90d": 7776000}
        cutoff_seconds = period_map.get(period, 604800)
        cutoff_ts = time.time() - cutoff_seconds

        recent = [e for e in self._events if e.get("ts", 0) >= cutoff_ts]

        revenue_events = [e for e in recent if e.get("event_type") == "revenue"]
        cost_events = [e for e in recent if e.get("event_type") == "cost"]
        conversion_events = [e for e in recent if e.get("event_type") == "conversion"]

        total_revenue = sum(e.get("amount_usd", 0.0) for e in revenue_events)
        total_costs = sum(e.get("amount_usd", 0.0) for e in cost_events)
        gross_profit = total_revenue - total_costs
        profit_margin_pct = (gross_profit / max(total_revenue, 0.01)) * 100

        roas_values = [e.get("value", 0.0) for e in conversion_events if e.get("metric") == "roas"]
        avg_roas = sum(roas_values) / max(len(roas_values), 1)

        cac_values = [e.get("value", 0.0) for e in recent if e.get("metric") == "cac"]
        avg_cac = sum(cac_values) / max(len(cac_values), 1)

        ltv_values = [e.get("value", 0.0) for e in recent if e.get("metric") == "ltv"]
        avg_ltv = sum(ltv_values) / max(len(ltv_values), 1)
        ltv_cac_ratio = avg_ltv / max(avg_cac, 0.01)

        cvr_values = [e.get("value", 0.0) for e in recent if e.get("metric") == "cvr"]
        avg_cvr = sum(cvr_values) / max(len(cvr_values), 1)

        computational_costs = sum(
            e.get("amount_usd", 0.0)
            for e in cost_events
            if e.get("context", {}).get("cost_type") == "ai_api"
        )

        efficiency_score = total_revenue / max(total_costs, 0.01)

        # Top revenue source
        revenue_by_src: dict[str, float] = {}
        for e in revenue_events:
            src = e.get("source", "unknown")
            revenue_by_src[src] = revenue_by_src.get(src, 0.0) + e.get("amount_usd", 0.0)
        top_revenue_source = max(revenue_by_src, key=revenue_by_src.get) if revenue_by_src else ""

        snap = EconomicSnapshot(
            period=period,
            total_revenue=total_revenue,
            total_costs=total_costs,
            gross_profit=gross_profit,
            profit_margin_pct=profit_margin_pct,
            avg_cac=avg_cac,
            avg_ltv=avg_ltv,
            ltv_cac_ratio=ltv_cac_ratio,
            avg_roas=avg_roas,
            avg_cvr=avg_cvr,
            computational_cost_usd=computational_costs,
            efficiency_score=efficiency_score,
            top_revenue_source=top_revenue_source,
        )
        self._snapshots.append(snap.to_dict())
        await self._save()
        return snap

    async def prioritize_by_roi(self, actions: list[dict]) -> list[dict]:
        """AI ranks list of actions by ROI score; returns sorted with 'roi_score' added."""
        await self._load()

        if not actions:
            return []

        actions_text = "\n".join(
            f"- {a.get('title', 'Unnamed')}: revenue=${a.get('estimated_revenue', 0)}, cost=${a.get('estimated_cost', 0)}"
            for a in actions
        )
        prompt = (
            f"Rank these business actions by ROI potential (0.0-1.0 score).\n"
            f"Actions:\n{actions_text}\n\n"
            f"Return ONLY a JSON array of objects with 'title' and 'roi_score' fields, ordered by roi_score descending."
        )

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system="You are a business ROI analyst. Return valid JSON only.",
                user=prompt,
                model=AIModel.FAST,
                max_tokens=500,
            )

            if resp.success:
                content = resp.content.strip()
                # Extract JSON array from response
                start = content.find("[")
                end = content.rfind("]") + 1
                if start >= 0 and end > start:
                    ranked = json.loads(content[start:end])
                    # Map scores back to actions
                    score_map = {r["title"]: r.get("roi_score", 0.5) for r in ranked}
                    for action in actions:
                        title = action.get("title", "")
                        action["roi_score"] = score_map.get(title, 0.5)
                    return sorted(actions, key=lambda a: a.get("roi_score", 0), reverse=True)
        except Exception:
            pass

        # Fallback: calculate simple ROI score
        for action in actions:
            revenue = action.get("estimated_revenue", 0)
            cost = action.get("estimated_cost", 1)
            roi = (revenue - cost) / max(cost, 0.01)
            action["roi_score"] = min(max(roi / 10, 0.0), 1.0)
        return sorted(actions, key=lambda a: a.get("roi_score", 0), reverse=True)

    def revenue_by_source(self) -> dict:
        """Sum revenue per source."""
        result: dict[str, float] = {}
        for e in self._events:
            if e.get("event_type") == "revenue":
                src = e.get("source", "unknown")
                result[src] = result.get(src, 0.0) + e.get("amount_usd", 0.0)
        return {k: round(v, 4) for k, v in result.items()}

    def cost_breakdown(self) -> dict:
        """Sum costs per source."""
        result: dict[str, float] = {}
        for e in self._events:
            if e.get("event_type") == "cost":
                src = e.get("source", "unknown")
                result[src] = result.get(src, 0.0) + e.get("amount_usd", 0.0)
        return {k: round(v, 4) for k, v in result.items()}

    def profitability_report(self) -> dict:
        """Full profitability breakdown."""
        revenue_by_src = self.revenue_by_source()
        cost_by_src = self.cost_breakdown()

        total_revenue = sum(revenue_by_src.values())
        total_costs = sum(cost_by_src.values())
        gross_profit = total_revenue - total_costs

        best_sources = sorted(
            [{"source": k, "revenue": v} for k, v in revenue_by_src.items()],
            key=lambda x: x["revenue"],
            reverse=True,
        )[:5]

        optimization_opportunities = []
        for src, cost in cost_by_src.items():
            rev = revenue_by_src.get(src, 0.0)
            if cost > 0 and rev < cost:
                optimization_opportunities.append({
                    "source": src,
                    "issue": "negative_roi",
                    "cost": round(cost, 4),
                    "revenue": round(rev, 4),
                    "deficit": round(cost - rev, 4),
                })

        return {
            "total_revenue": round(total_revenue, 4),
            "total_costs": round(total_costs, 4),
            "gross_profit": round(gross_profit, 4),
            "best_sources": best_sources,
            "optimization_opportunities": optimization_opportunities,
        }

    def economic_dashboard(self) -> dict:
        """Full dashboard with all key metrics."""
        revenue_by_src = self.revenue_by_source()
        cost_by_src = self.cost_breakdown()

        total_revenue = sum(revenue_by_src.values())
        total_costs = sum(cost_by_src.values())
        gross_profit = total_revenue - total_costs
        profit_margin = (gross_profit / max(total_revenue, 0.01)) * 100

        total_events = len(self._events)
        revenue_events = sum(1 for e in self._events if e.get("event_type") == "revenue")
        cost_events = sum(1 for e in self._events if e.get("event_type") == "cost")
        conversion_events = sum(1 for e in self._events if e.get("event_type") == "conversion")

        return {
            "summary": {
                "total_revenue": round(total_revenue, 4),
                "total_costs": round(total_costs, 4),
                "gross_profit": round(gross_profit, 4),
                "profit_margin_pct": round(profit_margin, 4),
                "efficiency_score": round(total_revenue / max(total_costs, 0.01), 4),
            },
            "revenue_by_source": revenue_by_src,
            "cost_breakdown": cost_by_src,
            "event_counts": {
                "total": total_events,
                "revenue": revenue_events,
                "cost": cost_events,
                "conversion": conversion_events,
            },
            "profitability": self.profitability_report(),
            "snapshots_count": len(self._snapshots),
        }

    def recent_events(self, limit: int = 20) -> list[dict]:
        """Return most recent events."""
        return sorted(self._events, key=lambda e: e.get("ts", 0), reverse=True)[:limit]


_instance: Optional[EconomicIntelligence] = None


def get_economic_intelligence() -> EconomicIntelligence:
    global _instance
    if _instance is None:
        _instance = EconomicIntelligence()
    return _instance
