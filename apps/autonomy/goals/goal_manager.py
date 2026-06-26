from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import StrEnum

from apps.core.memory.redis_client import get_cache

_TTL = 365 * 24 * 3600
_CACHE_KEY = "autonomy:goals:v1"


class GoalHorizon(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class GoalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ACHIEVED = "ACHIEVED"
    PAUSED = "PAUSED"
    ABANDONED = "ABANDONED"


@dataclass
class GoalMetric:
    name: str
    target: float
    current: float
    unit: str

    @property
    def progress_pct(self) -> float:
        return min(100.0, self.current / max(self.target, 0.01) * 100.0)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "target": self.target,
            "current": self.current,
            "unit": self.unit,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GoalMetric:
        return cls(
            name=data["name"],
            target=data["target"],
            current=data.get("current", 0.0),
            unit=data.get("unit", ""),
        )


@dataclass
class AutonomousGoal:
    goal_id: str
    title: str
    description: str
    horizon: GoalHorizon
    status: GoalStatus
    metrics: list[GoalMetric]
    priority: int
    created_at: float
    target_date_ts: float
    achieved_at: float = 0.0

    @property
    def overall_progress_pct(self) -> float:
        if not self.metrics:
            return 0.0
        return sum(m.progress_pct for m in self.metrics) / len(self.metrics)

    @property
    def days_remaining(self) -> int:
        return max(0, int((self.target_date_ts - time.time()) / 86400))

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "description": self.description,
            "horizon": self.horizon.value,
            "status": self.status.value,
            "metrics": [m.to_dict() for m in self.metrics],
            "priority": self.priority,
            "created_at": self.created_at,
            "target_date_ts": self.target_date_ts,
            "achieved_at": self.achieved_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AutonomousGoal:
        metrics = [GoalMetric.from_dict(m) for m in data.get("metrics", [])]
        return cls(
            goal_id=data["goal_id"],
            title=data["title"],
            description=data.get("description", ""),
            horizon=GoalHorizon(data["horizon"]),
            status=GoalStatus(data["status"]),
            metrics=metrics,
            priority=data.get("priority", 5),
            created_at=data.get("created_at", time.time()),
            target_date_ts=data.get("target_date_ts", time.time() + 30 * 86400),
            achieved_at=data.get("achieved_at", 0.0),
        )


_HORIZON_DAYS: dict[GoalHorizon, int] = {
    GoalHorizon.DAILY: 1,
    GoalHorizon.WEEKLY: 7,
    GoalHorizon.MONTHLY: 30,
    GoalHorizon.QUARTERLY: 90,
    GoalHorizon.ANNUAL: 365,
}


class GoalManager:
    def __init__(self) -> None:
        self._goals: dict[str, dict] = {}
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, dict):
                self._goals = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        self._loaded = True
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._goals, ttl_seconds=_TTL)
        except Exception:
            pass

    async def add_goal(
        self,
        title: str,
        horizon: GoalHorizon,
        metrics_data: list[dict],
        priority: int = 5,
        description: str = "",
    ) -> AutonomousGoal:
        await self._load()
        days = _HORIZON_DAYS.get(horizon, 30)
        metrics = [GoalMetric.from_dict(m) for m in metrics_data]
        goal = AutonomousGoal(
            goal_id=str(uuid.uuid4()),
            title=title,
            description=description,
            horizon=horizon,
            status=GoalStatus.ACTIVE,
            metrics=metrics,
            priority=priority,
            created_at=time.time(),
            target_date_ts=time.time() + days * 86400,
        )
        self._goals[goal.goal_id] = goal.to_dict()
        await self._save()
        return goal

    async def update_metric(
        self, goal_id: str, metric_name: str, current_value: float
    ) -> AutonomousGoal | None:
        await self._load()
        raw = self._goals.get(goal_id)
        if not raw:
            return None
        goal = AutonomousGoal.from_dict(raw)
        for metric in goal.metrics:
            if metric.name == metric_name:
                metric.current = current_value
                break
        if all(m.current >= m.target for m in goal.metrics):
            goal.status = GoalStatus.ACHIEVED
            goal.achieved_at = time.time()
        self._goals[goal_id] = goal.to_dict()
        await self._save()
        return goal

    async def get_active_goals(self, horizon: GoalHorizon | None = None) -> list[AutonomousGoal]:
        await self._load()
        goals: list[AutonomousGoal] = []
        for raw in self._goals.values():
            goal = AutonomousGoal.from_dict(raw)
            if goal.status != GoalStatus.ACTIVE:
                continue
            if horizon is not None and goal.horizon != horizon:
                continue
            goals.append(goal)
        return sorted(goals, key=lambda g: -g.priority)

    async def generate_default_goals(self) -> list[AutonomousGoal]:
        await self._load()
        if self._goals:
            return [AutonomousGoal.from_dict(v) for v in self._goals.values()]
        defaults = [
            {
                "title": "First $1K Revenue",
                "horizon": GoalHorizon.MONTHLY,
                "metrics": [
                    {"name": "revenue_usd", "target": 1000.0, "current": 0.0, "unit": "USD"}
                ],
                "priority": 10,
                "description": "Generate first $1,000 in revenue through product or service sales",
            },
            {
                "title": "100 Content Pieces",
                "horizon": GoalHorizon.QUARTERLY,
                "metrics": [
                    {"name": "content_count", "target": 100.0, "current": 0.0, "unit": "pieces"}
                ],
                "priority": 7,
                "description": "Publish 100 pieces of content across all channels",
            },
            {
                "title": "1,000 Email Subscribers",
                "horizon": GoalHorizon.QUARTERLY,
                "metrics": [
                    {
                        "name": "subscriber_count",
                        "target": 1000.0,
                        "current": 0.0,
                        "unit": "subscribers",
                    }
                ],
                "priority": 8,
                "description": "Build an email list of 1,000 engaged subscribers",
            },
            {
                "title": "Launch First Product",
                "horizon": GoalHorizon.MONTHLY,
                "metrics": [
                    {"name": "products_launched", "target": 1.0, "current": 0.0, "unit": "products"}
                ],
                "priority": 9,
                "description": "Launch first digital product or service offering",
            },
        ]
        created: list[AutonomousGoal] = []
        for d in defaults:
            goal = await self.add_goal(
                title=d["title"],
                horizon=d["horizon"],
                metrics_data=d["metrics"],
                priority=d["priority"],
                description=d["description"],
            )
            created.append(goal)
        return created

    async def goal_dashboard(self) -> dict:
        await self._load()
        active = 0
        achieved = 0
        at_risk: list[str] = []
        next_milestone = ""
        highest_priority: AutonomousGoal | None = None
        for raw in self._goals.values():
            goal = AutonomousGoal.from_dict(raw)
            if goal.status == GoalStatus.ACTIVE:
                active += 1
                if goal.days_remaining < 7 and goal.overall_progress_pct < 50.0:
                    at_risk.append(
                        f"{goal.title} ({goal.days_remaining}d left, {goal.overall_progress_pct:.0f}% done)"
                    )
                if highest_priority is None or goal.priority > highest_priority.priority:
                    highest_priority = goal
            elif goal.status == GoalStatus.ACHIEVED:
                achieved += 1
        if highest_priority:
            next_milestone = (
                f"{highest_priority.title}: "
                f"{highest_priority.overall_progress_pct:.0f}% complete, "
                f"{highest_priority.days_remaining} days remaining"
            )
        return {
            "active": active,
            "achieved": achieved,
            "at_risk": at_risk,
            "next_milestone": next_milestone,
        }

    def summary(self) -> dict:
        if not self._goals:
            return {"total_goals": 0, "active_goals": 0, "avg_progress_pct": 0.0}
        goals = [AutonomousGoal.from_dict(v) for v in self._goals.values()]
        active = [g for g in goals if g.status == GoalStatus.ACTIVE]
        avg_progress = sum(g.overall_progress_pct for g in active) / len(active) if active else 0.0
        return {
            "total_goals": len(goals),
            "active_goals": len(active),
            "avg_progress_pct": round(avg_progress, 2),
        }


_goal_manager_instance: GoalManager | None = None


def get_goal_manager() -> GoalManager:
    global _goal_manager_instance
    if _goal_manager_instance is None:
        _goal_manager_instance = GoalManager()
    return _goal_manager_instance
