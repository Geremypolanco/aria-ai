"""
ResourceAllocator — Budget and effort allocation across growth channels.
Uses performance data to shift resources toward highest-ROAS channels.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache

_KEY = "orchestration:resources:v1"
_TTL = 86400 * 60

_DEFAULT_SPLIT = {
    "content_seo": 0.25,
    "paid_ads": 0.35,
    "email_retention": 0.15,
    "shopify_optimization": 0.15,
    "influencer_affiliate": 0.10,
}


@dataclass
class ResourceAllocation:
    allocation_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    total_budget_usd: float = 0.0
    total_effort_hours: float = 0.0
    allocations: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "allocation_id": self.allocation_id,
            "total_budget_usd": self.total_budget_usd,
            "total_effort_hours": self.total_effort_hours,
            "allocations": self.allocations,
            "created_at": self.created_at,
        }


class ResourceAllocator:
    def __init__(self) -> None:
        self._allocations: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, list):
                    self._allocations = data
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, self._allocations[-100:], ttl_seconds=_TTL)
        except Exception:
            pass

    async def allocate(
        self, total_budget: float, total_hours: float, performance_data: dict = None
    ) -> ResourceAllocation:
        if performance_data is None:
            performance_data = {}
        await self._load()
        split = dict(_DEFAULT_SPLIT)

        # Adjust based on performance
        for channel, perf in performance_data.items():
            roas = perf.get("roas", 0.0)
            if channel in split:
                if roas > 3.0:
                    split[channel] = min(0.5, split[channel] * 1.2)
                elif roas < 1.0 and roas > 0:
                    split[channel] = max(0.05, split[channel] * 0.7)

        # Normalize
        total_split = sum(split.values())
        split = {k: v / total_split for k, v in split.items()}

        allocations = {}
        for channel, pct in split.items():
            perf = performance_data.get(channel, {})
            allocations[channel] = {
                "budget_usd": round(total_budget * pct, 2),
                "effort_hours": round(total_hours * pct, 1),
                "priority": "high" if pct >= 0.25 else "medium" if pct >= 0.12 else "low",
                "rationale": f"{pct*100:.0f}% allocation",
                "current_roas": perf.get("roas", 0.0),
            }

        allocation = ResourceAllocation(
            total_budget_usd=total_budget,
            total_effort_hours=total_hours,
            allocations=allocations,
        )
        self._allocations.append(allocation.to_dict())
        await self._save()
        return allocation

    async def optimize_allocation(self, campaigns: list[dict]) -> ResourceAllocation:
        performance_data = {}
        for c in campaigns:
            ch = c.get("channel", "")
            if ch:
                performance_data[ch] = {
                    "spend": c.get("spend", 0),
                    "revenue": c.get("revenue", 0),
                    "roas": c.get("roas", 0.0)
                    or (c["revenue"] / c["spend"] if c.get("spend", 0) > 0 else 0.0),
                }
        total_budget = sum(c.get("spend", 0) for c in campaigns)
        total_hours = len(campaigns) * 5.0
        return await self.allocate(total_budget, total_hours, performance_data)

    def pareto_channels(self, performance_data: dict) -> list[str]:
        if not performance_data:
            return ["content_seo", "paid_ads"]
        revenues = [(ch, p.get("revenue", 0)) for ch, p in performance_data.items()]
        revenues.sort(key=lambda x: x[1], reverse=True)
        total_revenue = sum(r for _, r in revenues)
        pareto_channels = []
        cumulative = 0.0
        for ch, rev in revenues:
            pareto_channels.append(ch)
            cumulative += rev
            if total_revenue > 0 and cumulative / total_revenue >= 0.8:
                break
        return pareto_channels

    def allocation_history(self) -> list[dict]:
        return list(reversed(self._allocations[-20:]))

    def efficiency_report(self) -> dict:
        if not self._allocations:
            return {"total_allocations": 0}
        latest = self._allocations[-1]
        allocs = latest.get("allocations", {})
        by_channel = {
            ch: {
                "budget_pct": (
                    round(a["budget_usd"] / latest["total_budget_usd"] * 100, 1)
                    if latest["total_budget_usd"] > 0
                    else 0
                ),
                "roas": a.get("current_roas", 0.0),
                "priority": a.get("priority", "medium"),
            }
            for ch, a in allocs.items()
        }
        top_channel = (
            max(allocs, key=lambda ch: allocs[ch].get("budget_usd", 0)) if allocs else "none"
        )
        return {
            "total_allocations": len(self._allocations),
            "by_channel": by_channel,
            "recommended_reallocation": f"Increase {top_channel} if ROAS > 3.0",
        }


_instance: ResourceAllocator | None = None


def get_resource_allocator() -> ResourceAllocator:
    global _instance
    if _instance is None:
        _instance = ResourceAllocator()
    return _instance
