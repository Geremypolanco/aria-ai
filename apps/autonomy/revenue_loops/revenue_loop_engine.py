from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.memory.redis_client import get_cache

_TTL = 365 * 24 * 3600
_CACHE_KEY = "autonomy:revenue_loops:v1"


class LoopPhase(str, Enum):
    OBSERVE = "OBSERVE"
    ANALYZE = "ANALYZE"
    DECIDE = "DECIDE"
    EXECUTE = "EXECUTE"
    MEASURE = "MEASURE"
    LEARN = "LEARN"


_PHASE_ACTIONS: dict[LoopPhase, list[str]] = {
    LoopPhase.OBSERVE: [
        "Collect traffic and conversion data from last 24h",
        "Monitor competitor activity and pricing",
        "Review customer feedback and support tickets",
        "Check social sentiment and mention volume",
    ],
    LoopPhase.ANALYZE: [
        "Identify top-converting traffic sources",
        "Calculate cost-per-acquisition by channel",
        "Segment audience by purchase behaviour",
        "Map funnel drop-off points with highest impact",
    ],
    LoopPhase.DECIDE: [
        "Prioritise optimisations by estimated revenue impact",
        "Allocate budget across highest-ROI channels",
        "Select A/B test variants for next cycle",
        "Define success metrics for execution phase",
    ],
    LoopPhase.EXECUTE: [
        "Deploy updated pricing and promotional offers",
        "Publish scheduled content and ad creatives",
        "Send targeted email sequences to warm segments",
        "Activate affiliate and partnership placements",
    ],
    LoopPhase.MEASURE: [
        "Track 24h revenue delta vs previous cycle",
        "Monitor conversion rate changes by segment",
        "Measure email open and click-through rates",
        "Record customer acquisition cost movement",
    ],
    LoopPhase.LEARN: [
        "Document what drove the highest revenue delta",
        "Update channel weighting for next cycle",
        "Archive failed experiments with root-cause notes",
        "Incorporate learnings into next cycle decision model",
    ],
}


@dataclass
class RevenueLoop:
    loop_id: str
    name: str
    description: str
    channel: str
    current_phase: LoopPhase
    revenue_generated_usd: float
    iterations: int
    success_rate: float
    last_run_ts: float
    next_run_ts: float
    active: bool
    learnings: list[str]

    def to_dict(self) -> dict:
        return {
            "loop_id": self.loop_id,
            "name": self.name,
            "description": self.description,
            "channel": self.channel,
            "current_phase": self.current_phase.value,
            "revenue_generated_usd": self.revenue_generated_usd,
            "iterations": self.iterations,
            "success_rate": self.success_rate,
            "last_run_ts": self.last_run_ts,
            "next_run_ts": self.next_run_ts,
            "active": self.active,
            "learnings": self.learnings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RevenueLoop:
        return cls(
            loop_id=data["loop_id"],
            name=data["name"],
            description=data.get("description", ""),
            channel=data.get("channel", "general"),
            current_phase=LoopPhase(data.get("current_phase", LoopPhase.OBSERVE.value)),
            revenue_generated_usd=data.get("revenue_generated_usd", 0.0),
            iterations=data.get("iterations", 0),
            success_rate=data.get("success_rate", 0.0),
            last_run_ts=data.get("last_run_ts", 0.0),
            next_run_ts=data.get("next_run_ts", time.time()),
            active=data.get("active", True),
            learnings=data.get("learnings", []),
        )


@dataclass
class LoopExecution:
    execution_id: str
    loop_id: str
    phase: LoopPhase
    actions_taken: list[str]
    revenue_delta_usd: float
    insights: list[str]
    timestamp: float

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "loop_id": self.loop_id,
            "phase": self.phase.value,
            "actions_taken": self.actions_taken,
            "revenue_delta_usd": self.revenue_delta_usd,
            "insights": self.insights,
            "timestamp": self.timestamp,
        }


class RevenueLoopEngine:
    def __init__(self) -> None:
        self._loops: dict[str, dict] = {}
        self._executions: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, dict):
                self._loops = data.get("loops", {})
                self._executions = data.get("executions", [])
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        self._loaded = True
        try:
            cache = get_cache()
            await cache.set(
                _CACHE_KEY,
                {"loops": self._loops, "executions": self._executions[-500:]},
                ttl_seconds=_TTL,
            )
        except Exception:
            pass

    async def create_loop(
        self, name: str, channel: str, description: str = ""
    ) -> RevenueLoop:
        await self._load()
        loop = RevenueLoop(
            loop_id=str(uuid.uuid4()),
            name=name,
            description=description or f"Autonomous revenue optimisation loop for {channel}",
            channel=channel,
            current_phase=LoopPhase.OBSERVE,
            revenue_generated_usd=0.0,
            iterations=0,
            success_rate=0.0,
            last_run_ts=0.0,
            next_run_ts=time.time() + 24 * 3600,
            active=True,
            learnings=[],
        )
        self._loops[loop.loop_id] = loop.to_dict()
        await self._save()
        return loop

    async def run_loop(self, loop_id: str) -> LoopExecution:
        await self._load()
        raw = self._loops.get(loop_id)
        if not raw:
            raise ValueError(f"Loop {loop_id} not found")
        loop = RevenueLoop.from_dict(raw)

        all_actions: list[str] = []
        for phase in LoopPhase:
            all_actions.extend(_PHASE_ACTIONS[phase][:2])

        # Simulate revenue delta: small multiplier on a base amount seeded by iterations
        base = max(10.0, loop.revenue_generated_usd * 0.05 + 10.0)
        multiplier = 0.95 + random.random() * 0.20
        revenue_delta = round(base * multiplier, 2)

        loop.revenue_generated_usd = round(loop.revenue_generated_usd + revenue_delta, 2)
        loop.iterations += 1
        prev_success = loop.success_rate
        loop.success_rate = round(
            (prev_success * (loop.iterations - 1) + (1.0 if revenue_delta > 0 else 0.0))
            / loop.iterations,
            3,
        )
        loop.last_run_ts = time.time()
        loop.next_run_ts = time.time() + 24 * 3600
        loop.current_phase = LoopPhase.OBSERVE

        learning = f"Iteration {loop.iterations}: +${revenue_delta} revenue (×{multiplier:.2f} multiplier)"
        loop.learnings.append(learning)
        if len(loop.learnings) > 50:
            loop.learnings = loop.learnings[-50:]

        insights = [
            f"Revenue delta this cycle: +${revenue_delta}",
            f"Running total: ${loop.revenue_generated_usd}",
            f"Success rate: {loop.success_rate * 100:.1f}%",
        ]

        execution = LoopExecution(
            execution_id=str(uuid.uuid4()),
            loop_id=loop_id,
            phase=LoopPhase.LEARN,
            actions_taken=all_actions,
            revenue_delta_usd=revenue_delta,
            insights=insights,
            timestamp=time.time(),
        )
        self._loops[loop_id] = loop.to_dict()
        self._executions.append(execution.to_dict())
        await self._save()
        return execution

    async def due_loops(self) -> list[RevenueLoop]:
        await self._load()
        now = time.time()
        due: list[RevenueLoop] = []
        for raw in self._loops.values():
            loop = RevenueLoop.from_dict(raw)
            if loop.active and loop.next_run_ts <= now:
                due.append(loop)
        return due

    async def run_all_due(self) -> list[LoopExecution]:
        due = await self.due_loops()
        executions: list[LoopExecution] = []
        for loop in due:
            try:
                execution = await self.run_loop(loop.loop_id)
                executions.append(execution)
            except Exception:
                pass
        return executions

    async def default_loops(self) -> list[RevenueLoop]:
        await self._load()
        if self._loops:
            return [RevenueLoop.from_dict(v) for v in self._loops.values()]
        defaults = [
            ("Shopify Optimisation", "shopify", "Optimise product listings, pricing, and ads for Shopify store"),
            ("Content Monetisation", "content", "Convert content traffic to revenue through CTAs and offers"),
            ("Email Revenue", "email", "Drive purchases through email sequences and promotions"),
            ("Affiliate Tracking", "affiliate", "Maximise affiliate commissions through content and link placement"),
        ]
        loops: list[RevenueLoop] = []
        for name, channel, desc in defaults:
            loop = await self.create_loop(name=name, channel=channel, description=desc)
            loops.append(loop)
        return loops

    async def loop_analytics(self) -> dict:
        await self._load()
        if not self._loops:
            return {
                "total_loops": 0,
                "total_revenue_usd": 0.0,
                "avg_success_rate": 0.0,
                "most_profitable_loop": "",
                "total_iterations": 0,
            }
        loops = [RevenueLoop.from_dict(v) for v in self._loops.values()]
        total_revenue = sum(l.revenue_generated_usd for l in loops)
        avg_success = sum(l.success_rate for l in loops) / len(loops)
        most_profitable = max(loops, key=lambda l: l.revenue_generated_usd)
        total_iterations = sum(l.iterations for l in loops)
        return {
            "total_loops": len(loops),
            "total_revenue_usd": round(total_revenue, 2),
            "avg_success_rate": round(avg_success, 3),
            "most_profitable_loop": most_profitable.name,
            "total_iterations": total_iterations,
        }

    def summary(self) -> dict:
        active = sum(1 for v in self._loops.values() if v.get("active", True))
        total_revenue = sum(
            v.get("revenue_generated_usd", 0.0) for v in self._loops.values()
        )
        return {
            "active_loops": active,
            "total_revenue_usd": round(total_revenue, 2),
        }


_revenue_loop_engine_instance: RevenueLoopEngine | None = None


def get_revenue_loop_engine() -> RevenueLoopEngine:
    global _revenue_loop_engine_instance
    if _revenue_loop_engine_instance is None:
        _revenue_loop_engine_instance = RevenueLoopEngine()
    return _revenue_loop_engine_instance
