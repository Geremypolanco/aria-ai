"""
CEO Agent — Strategic decision-making, growth targets, and vision.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_KEY = "executive:ceo:v1"
_TTL = 90 * 24 * 3600  # 90 days


@dataclass
class StrategicDecision:
    decision_id: str
    title: str
    description: str
    rationale: str
    priority: int  # 1-10
    estimated_revenue_impact: float
    estimated_effort_hours: float
    roi_score: float
    approved: bool
    created_at: float

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "title": self.title,
            "description": self.description,
            "rationale": self.rationale,
            "priority": self.priority,
            "estimated_revenue_impact": self.estimated_revenue_impact,
            "estimated_effort_hours": self.estimated_effort_hours,
            "roi_score": self.roi_score,
            "approved": self.approved,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StrategicDecision:
        return cls(
            decision_id=data["decision_id"],
            title=data["title"],
            description=data.get("description", ""),
            rationale=data.get("rationale", ""),
            priority=data.get("priority", 5),
            estimated_revenue_impact=data.get("estimated_revenue_impact", 0.0),
            estimated_effort_hours=data.get("estimated_effort_hours", 0.0),
            roi_score=data.get("roi_score", 0.0),
            approved=data.get("approved", False),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class GrowthTarget:
    target_id: str
    metric: str
    current_value: float
    target_value: float
    deadline_days: int
    status: str  # "active" | "achieved" | "missed"

    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "metric": self.metric,
            "current_value": self.current_value,
            "target_value": self.target_value,
            "deadline_days": self.deadline_days,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GrowthTarget:
        return cls(
            target_id=data["target_id"],
            metric=data["metric"],
            current_value=data.get("current_value", 0.0),
            target_value=data.get("target_value", 0.0),
            deadline_days=data.get("deadline_days", 30),
            status=data.get("status", "active"),
        )


class CEOAgent:
    def __init__(self) -> None:
        self._decisions: list[dict] = []
        self._targets: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._decisions = data.get("decisions", [])
                    self._targets = data.get("targets", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            payload = {
                "decisions": self._decisions[-200:],
                "targets": self._targets[-200:],
            }
            await cache.set(_KEY, payload, ttl_seconds=_TTL)
        except Exception:
            pass

    async def set_growth_target(
        self,
        metric: str,
        current: float,
        target: float,
        deadline_days: int,
    ) -> GrowthTarget:
        await self._load()
        gt = GrowthTarget(
            target_id=str(uuid.uuid4()),
            metric=metric,
            current_value=current,
            target_value=target,
            deadline_days=deadline_days,
            status="active",
        )
        self._targets.append(gt.to_dict())
        await self._save()
        return gt

    async def make_strategic_decision(self, context: dict, options: list[str]) -> StrategicDecision:
        await self._load()
        options_text = "\n".join(f"{i+1}. {o}" for i, o in enumerate(options))
        context_text = "; ".join(f"{k}: {v}" for k, v in context.items())
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are the CEO of an AI-powered online business. "
                "Evaluate the options and pick the best one for maximum ROI. "
                "Reply with: CHOICE: <chosen option> | RATIONALE: <brief reason> | "
                "PRIORITY: <1-10> | REVENUE_IMPACT: <usd estimate> | "
                "EFFORT_HOURS: <hours estimate>"
            ),
            user=f"Context: {context_text}\n\nOptions:\n{options_text}",
            model=AIModel.STRATEGY,
            max_tokens=300,
        )
        content = resp.content if resp.success else ""

        # Parse AI response
        chosen = options[0] if options else "No option"
        rationale = content
        priority = 7
        revenue_impact = 1000.0
        effort_hours = 10.0

        if "CHOICE:" in content:
            try:
                parts = content.split("|")
                chosen = parts[0].split("CHOICE:")[-1].strip()
                for part in parts:
                    part = part.strip()
                    if part.startswith("RATIONALE:"):
                        rationale = part.split("RATIONALE:")[-1].strip()
                    elif part.startswith("PRIORITY:"):
                        priority = int(part.split("PRIORITY:")[-1].strip().split()[0])
                        priority = max(1, min(10, priority))
                    elif part.startswith("REVENUE_IMPACT:"):
                        val = part.split("REVENUE_IMPACT:")[-1].strip()
                        revenue_impact = float(
                            "".join(c for c in val if c.isdigit() or c == ".") or "1000"
                        )
                    elif part.startswith("EFFORT_HOURS:"):
                        val = part.split("EFFORT_HOURS:")[-1].strip()
                        effort_hours = float(
                            "".join(c for c in val if c.isdigit() or c == ".") or "10"
                        )
            except Exception:
                pass

        roi_score = round(revenue_impact / max(effort_hours, 1), 2)

        decision = StrategicDecision(
            decision_id=str(uuid.uuid4()),
            title=chosen[:100],
            description=f"Strategic decision from options: {', '.join(options)}",
            rationale=rationale,
            priority=priority,
            estimated_revenue_impact=revenue_impact,
            estimated_effort_hours=effort_hours,
            roi_score=roi_score,
            approved=True,
            created_at=time.time(),
        )
        self._decisions.append(decision.to_dict())
        await self._save()
        return decision

    async def prioritize_departments(self, department_metrics: dict) -> list[dict]:
        await self._load()
        ai = get_ai_client()
        metrics_text = "; ".join(f"{dept}: {vals}" for dept, vals in department_metrics.items())
        resp = await ai.complete(
            system=(
                "You are the CEO. Rank departments by ROI potential. "
                "Return a comma-separated list of department names from highest to lowest priority."
            ),
            user=f"Department metrics: {metrics_text}",
            model=AIModel.FAST,
            max_tokens=200,
        )
        content = resp.content if resp.success else ""
        dept_names = list(department_metrics.keys())
        if content:
            parsed = [d.strip() for d in content.replace("\n", ",").split(",") if d.strip()]
            matched = []
            seen = set()
            for name in parsed:
                for dept in dept_names:
                    if dept.lower() in name.lower() or name.lower() in dept.lower():
                        if dept not in seen:
                            matched.append(dept)
                            seen.add(dept)
            for dept in dept_names:
                if dept not in seen:
                    matched.append(dept)
            dept_names = matched

        result = []
        for rank, dept in enumerate(dept_names, 1):
            result.append(
                {
                    "rank": rank,
                    "department": dept,
                    "metrics": department_metrics.get(dept, {}),
                    "priority_score": round(10 - (rank - 1) * (10 / max(len(dept_names), 1)), 1),
                }
            )
        return result

    async def weekly_vision_statement(self, niche: str) -> str:
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a visionary CEO. Write a concise, inspiring weekly vision statement "
                "for the team. Focus on growth, execution, and winning in the market."
            ),
            user=f"Our niche: {niche}. Write the vision statement for this week.",
            model=AIModel.CREATIVE,
            max_tokens=200,
        )
        return (
            resp.content
            if resp.success
            else f"This week we dominate {niche} through relentless execution."
        )

    def active_targets(self) -> list[dict]:
        return [t for t in self._targets if t.get("status") == "active"]

    def decision_log(self) -> list[dict]:
        return list(self._decisions)

    def strategic_summary(self) -> dict:
        decisions = [StrategicDecision.from_dict(d) for d in self._decisions]
        approved = [d for d in decisions if d.approved]
        avg_roi = sum(d.roi_score for d in decisions) / len(decisions) if decisions else 0.0
        return {
            "total_decisions": len(decisions),
            "approved_ratio": round(len(approved) / max(len(decisions), 1), 2),
            "avg_roi_score": round(avg_roi, 2),
            "active_targets": len(self.active_targets()),
        }


_instance: CEOAgent | None = None


def get_ceo_agent() -> CEOAgent:
    global _instance
    if _instance is None:
        _instance = CEOAgent()
    return _instance
