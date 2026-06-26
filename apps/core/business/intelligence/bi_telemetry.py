"""
Business Intelligence Telemetry — economic observability layer.

Tracks: ROI per workflow, revenue attribution by agent/tool/strategy,
workflow profitability, agent productivity scores, cognition cost efficiency.

All metrics are time-windowed so dashboards show trends, not just totals.
Data is persisted to Redis (30-day TTL) and queried via summary/report methods.

Design: pull-based. Callers record_* after each operation; dashboard/API
queries summary() or report(window_hours=24) on demand.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class WorkflowRecord:
    workflow_id: str
    workflow_type: str
    agent_id: str
    strategy: str
    revenue_usd: float
    cost_usd: float
    duration_ms: float
    success: bool
    ts: float
    tools_used: list[str] = field(default_factory=list)

    @property
    def profit_usd(self) -> float:
        return self.revenue_usd - self.cost_usd

    @property
    def roi_multiple(self) -> float:
        if self.cost_usd <= 0:
            return 0.0
        return self.revenue_usd / self.cost_usd

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "workflow_type": self.workflow_type,
            "agent_id": self.agent_id,
            "strategy": self.strategy,
            "revenue_usd": self.revenue_usd,
            "cost_usd": self.cost_usd,
            "profit_usd": self.profit_usd,
            "roi_multiple": round(self.roi_multiple, 2),
            "duration_ms": self.duration_ms,
            "success": self.success,
            "ts": self.ts,
            "tools_used": self.tools_used,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WorkflowRecord:
        return cls(
            workflow_id=d["workflow_id"],
            workflow_type=d.get("workflow_type", "unknown"),
            agent_id=d.get("agent_id", "unknown"),
            strategy=d.get("strategy", "unknown"),
            revenue_usd=float(d.get("revenue_usd", 0)),
            cost_usd=float(d.get("cost_usd", 0)),
            duration_ms=float(d.get("duration_ms", 0)),
            success=bool(d.get("success", True)),
            ts=float(d.get("ts", time.time())),
            tools_used=d.get("tools_used", []),
        )


class BITelemetry:
    """
    Business Intelligence metric collector and reporter.

    Workflow records are kept in-memory (capped at 10k) and also persisted
    to Redis for cross-process / cross-restart visibility.
    """

    _REDIS_KEY = "bi_telemetry:workflows:v1"
    _MAX_IN_MEMORY = 10_000

    def __init__(self) -> None:
        self._workflows: list[WorkflowRecord] = []
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            from apps.core.memory.redis_client import get_cache

            raw = await get_cache().get(self._REDIS_KEY)
            if raw and isinstance(raw, list):
                self._workflows = [WorkflowRecord.from_dict(d) for d in raw[-self._MAX_IN_MEMORY :]]
        except Exception:
            pass
        self._loaded = True

    async def _persist(self) -> None:
        try:
            from apps.core.memory.redis_client import get_cache

            payload = [w.to_dict() for w in self._workflows[-self._MAX_IN_MEMORY :]]
            await get_cache().set(self._REDIS_KEY, payload, ttl_seconds=60 * 60 * 24 * 30)
        except Exception:
            pass

    # ── Recording ─────────────────────────────────────────────────────────────

    async def record_workflow(
        self,
        workflow_type: str,
        agent_id: str,
        strategy: str,
        revenue_usd: float,
        cost_usd: float = 0.0,
        duration_ms: float = 0.0,
        success: bool = True,
        tools_used: list[str] | None = None,
        workflow_id: str | None = None,
    ) -> str:
        await self._ensure_loaded()
        rec = WorkflowRecord(
            workflow_id=workflow_id or f"wf_{uuid.uuid4().hex[:8]}",
            workflow_type=workflow_type,
            agent_id=agent_id,
            strategy=strategy,
            revenue_usd=revenue_usd,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            success=success,
            ts=time.time(),
            tools_used=tools_used or [],
        )
        self._workflows.append(rec)
        if len(self._workflows) > self._MAX_IN_MEMORY:
            self._workflows = self._workflows[-self._MAX_IN_MEMORY :]
        await self._persist()
        return rec.workflow_id

    # ── Reporting ─────────────────────────────────────────────────────────────

    async def report(self, window_hours: float = 24.0) -> dict:
        await self._ensure_loaded()
        cutoff = time.time() - window_hours * 3600
        window_wf = [w for w in self._workflows if w.ts >= cutoff]

        if not window_wf:
            return {"window_hours": window_hours, "total_workflows": 0, "revenue": 0, "profit": 0}

        total_rev = sum(w.revenue_usd for w in window_wf)
        total_cost = sum(w.cost_usd for w in window_wf)
        total_profit = sum(w.profit_usd for w in window_wf)
        success_count = sum(1 for w in window_wf if w.success)

        by_agent: dict[str, dict] = defaultdict(
            lambda: {"revenue": 0.0, "workflows": 0, "success": 0}
        )
        by_strategy: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "workflows": 0})
        by_type: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "workflows": 0})
        tool_revenue: dict[str, float] = defaultdict(float)

        for w in window_wf:
            by_agent[w.agent_id]["revenue"] += w.revenue_usd
            by_agent[w.agent_id]["workflows"] += 1
            by_agent[w.agent_id]["success"] += int(w.success)
            by_strategy[w.strategy]["revenue"] += w.revenue_usd
            by_strategy[w.strategy]["workflows"] += 1
            by_type[w.workflow_type]["revenue"] += w.revenue_usd
            by_type[w.workflow_type]["workflows"] += 1
            for tool in w.tools_used:
                tool_revenue[tool] += w.revenue_usd / max(len(w.tools_used), 1)

        agent_productivity = {
            aid: {
                "revenue": round(d["revenue"], 2),
                "workflows": d["workflows"],
                "success_rate": round(d["success"] / d["workflows"], 3),
                "revenue_per_workflow": round(d["revenue"] / d["workflows"], 2),
            }
            for aid, d in by_agent.items()
        }

        top_agent = (
            max(agent_productivity, key=lambda k: agent_productivity[k]["revenue"])
            if agent_productivity
            else None
        )
        top_strategy = (
            max(by_strategy, key=lambda k: by_strategy[k]["revenue"]) if by_strategy else None
        )

        return {
            "window_hours": window_hours,
            "total_workflows": len(window_wf),
            "success_rate": round(success_count / len(window_wf), 3),
            "revenue_usd": round(total_rev, 2),
            "cost_usd": round(total_cost, 2),
            "profit_usd": round(total_profit, 2),
            "avg_roi_multiple": round(total_rev / max(total_cost, 0.01), 2),
            "revenue_per_workflow": round(total_rev / len(window_wf), 2),
            "top_agent": top_agent,
            "top_strategy": top_strategy,
            "by_agent": agent_productivity,
            "by_strategy": {
                k: {"revenue": round(v["revenue"], 2), "workflows": v["workflows"]}
                for k, v in by_strategy.items()
            },
            "by_type": {
                k: {"revenue": round(v["revenue"], 2), "workflows": v["workflows"]}
                for k, v in by_type.items()
            },
            "tool_revenue_attribution": {
                k: round(v, 2) for k, v in sorted(tool_revenue.items(), key=lambda x: -x[1])[:10]
            },
        }

    def summary(self) -> dict:
        all_wf = self._workflows
        if not all_wf:
            return {"total_workflows": 0}
        return {
            "total_workflows": len(all_wf),
            "total_revenue_usd": round(sum(w.revenue_usd for w in all_wf), 2),
            "total_profit_usd": round(sum(w.profit_usd for w in all_wf), 2),
            "overall_success_rate": round(sum(1 for w in all_wf if w.success) / len(all_wf), 3),
            "unique_agents": len({w.agent_id for w in all_wf}),
            "unique_strategies": len({w.strategy for w in all_wf}),
        }


_bi: BITelemetry | None = None


def get_bi_telemetry() -> BITelemetry:
    global _bi
    if _bi is None:
        _bi = BITelemetry()
    return _bi
