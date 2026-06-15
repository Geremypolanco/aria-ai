"""
COO Agent — Operational metrics, workflow assessment, and department coordination.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_KEY = "executive:coo:v1"
_TTL = 90 * 24 * 3600  # 90 days


@dataclass
class OperationalMetric:
    metric_id: str
    name: str
    value: float
    unit: str
    dept: str
    target: float
    status: str  # "on_track" | "at_risk" | "critical"
    ts: float

    def to_dict(self) -> dict:
        return {
            "metric_id": self.metric_id,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "dept": self.dept,
            "target": self.target,
            "status": self.status,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OperationalMetric":
        return cls(
            metric_id=data["metric_id"],
            name=data["name"],
            value=data.get("value", 0.0),
            unit=data.get("unit", ""),
            dept=data.get("dept", ""),
            target=data.get("target", 0.0),
            status=data.get("status", "on_track"),
            ts=data.get("ts", time.time()),
        )


@dataclass
class WorkflowStatus:
    workflow_id: str
    name: str
    dept: str
    tasks_total: int
    tasks_done: int
    efficiency_score: float
    bottleneck: str

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "dept": self.dept,
            "tasks_total": self.tasks_total,
            "tasks_done": self.tasks_done,
            "efficiency_score": self.efficiency_score,
            "bottleneck": self.bottleneck,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowStatus":
        return cls(
            workflow_id=data["workflow_id"],
            name=data["name"],
            dept=data.get("dept", ""),
            tasks_total=data.get("tasks_total", 0),
            tasks_done=data.get("tasks_done", 0),
            efficiency_score=data.get("efficiency_score", 0.0),
            bottleneck=data.get("bottleneck", ""),
        )


class COOAgent:
    def __init__(self) -> None:
        self._metrics: list[dict] = []
        self._workflows: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._metrics = data.get("metrics", [])
                    self._workflows = data.get("workflows", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            payload = {
                "metrics": self._metrics[-200:],
                "workflows": self._workflows[-200:],
            }
            await cache.set(_KEY, payload, ttl_seconds=_TTL)
        except Exception:
            pass

    def _compute_status(self, value: float, target: float) -> str:
        if target <= 0:
            return "on_track"
        ratio = value / target
        if ratio >= 0.85:
            return "on_track"
        elif ratio >= 0.60:
            return "at_risk"
        return "critical"

    async def track_metric(
        self,
        name: str,
        value: float,
        unit: str,
        dept: str,
        target: float,
    ) -> OperationalMetric:
        await self._load()
        status = self._compute_status(value, target)
        metric = OperationalMetric(
            metric_id=str(uuid.uuid4()),
            name=name,
            value=value,
            unit=unit,
            dept=dept,
            target=target,
            status=status,
            ts=time.time(),
        )
        self._metrics.append(metric.to_dict())
        await self._save()
        return metric

    async def assess_workflow(self, dept: str, tasks: list[dict]) -> WorkflowStatus:
        await self._load()
        tasks_total = len(tasks)
        tasks_done = sum(1 for t in tasks if t.get("done") or t.get("status") == "done")
        efficiency_score = round(tasks_done / max(tasks_total, 1) * 100, 1)

        ai = get_ai_client()
        tasks_text = "; ".join(
            f"{t.get('name', 'task')}: {'done' if t.get('done') else 'pending'}"
            for t in tasks[:10]
        )
        resp = await ai.complete(
            system=(
                "You are the COO. Identify the main operational bottleneck in this workflow. "
                "Reply with one concise sentence naming the bottleneck."
            ),
            user=f"Department: {dept}\nTasks: {tasks_text}\nDone: {tasks_done}/{tasks_total}",
            model=AIModel.FAST,
            max_tokens=100,
        )
        bottleneck = resp.content.strip() if resp.success else "Insufficient task completion rate"

        wf = WorkflowStatus(
            workflow_id=str(uuid.uuid4()),
            name=f"{dept} workflow",
            dept=dept,
            tasks_total=tasks_total,
            tasks_done=tasks_done,
            efficiency_score=efficiency_score,
            bottleneck=bottleneck,
        )
        self._workflows.append(wf.to_dict())
        await self._save()
        return wf

    async def coordinate_departments(self, priorities: list[dict]) -> dict:
        ai = get_ai_client()
        priorities_text = "; ".join(
            f"{p.get('department', p.get('dept', 'unknown'))}: priority {p.get('rank', p.get('priority_score', 'N/A'))}"
            for p in priorities
        )
        resp = await ai.complete(
            system=(
                "You are the COO. Create a concise coordination plan for the departments. "
                "Focus on synergies, resource sharing, and bottleneck removal."
            ),
            user=f"Department priorities: {priorities_text}",
            model=AIModel.STRATEGY,
            max_tokens=300,
        )
        plan_text = resp.content if resp.success else "Coordinate departments sequentially by priority."
        return {
            "coordination_plan": plan_text,
            "departments_count": len(priorities),
            "priorities": priorities,
            "created_at": time.time(),
        }

    def department_health(self) -> dict:
        health: dict[str, dict] = {}
        for m_dict in self._metrics:
            m = OperationalMetric.from_dict(m_dict)
            dept = m.dept
            if dept not in health:
                health[dept] = {"on_track": 0, "at_risk": 0, "critical": 0, "total": 0}
            health[dept][m.status] = health[dept].get(m.status, 0) + 1
            health[dept]["total"] += 1
        return health

    def at_risk_metrics(self) -> list[dict]:
        return [
            m for m in self._metrics
            if m.get("status") in ("at_risk", "critical")
        ]

    def operations_report(self) -> dict:
        metrics = [OperationalMetric.from_dict(m) for m in self._metrics]
        at_risk = sum(1 for m in metrics if m.status == "at_risk")
        critical = sum(1 for m in metrics if m.status == "critical")
        workflows = [WorkflowStatus.from_dict(w) for w in self._workflows]
        avg_eff = (
            sum(w.efficiency_score for w in workflows) / len(workflows)
            if workflows else 0.0
        )
        return {
            "total_metrics": len(metrics),
            "at_risk": at_risk,
            "critical": critical,
            "avg_efficiency": round(avg_eff, 1),
        }


_instance: Optional[COOAgent] = None


def get_coo_agent() -> COOAgent:
    global _instance
    if _instance is None:
        _instance = COOAgent()
    return _instance
