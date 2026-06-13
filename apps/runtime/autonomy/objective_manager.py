from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.memory.redis_client import get_cache

_OBJECTIVES_KEY = "objectives:long:v1"
_OBJECTIVES_TTL = 86400 * 365


class Horizon(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class MilestoneStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    ACHIEVED = "achieved"
    MISSED = "missed"


@dataclass
class Milestone:
    milestone_id: str
    title: str
    target_date_ts: float
    metric: str
    target_value: float
    current_value: float = 0.0
    status: MilestoneStatus = MilestoneStatus.PENDING

    @property
    def progress_pct(self) -> float:
        if self.target_value <= 0:
            return 0.0
        return min(100.0, self.current_value / self.target_value * 100)

    def to_dict(self) -> dict:
        return {
            "milestone_id": self.milestone_id,
            "title": self.title,
            "target_date_ts": self.target_date_ts,
            "metric": self.metric,
            "target_value": self.target_value,
            "current_value": self.current_value,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Milestone:
        return cls(
            milestone_id=d["milestone_id"],
            title=d["title"],
            target_date_ts=d["target_date_ts"],
            metric=d["metric"],
            target_value=d["target_value"],
            current_value=d.get("current_value", 0.0),
            status=MilestoneStatus(d.get("status", MilestoneStatus.PENDING.value)),
        )


@dataclass
class LongHorizonObjective:
    obj_id: str
    title: str
    horizon: Horizon
    description: str
    milestones: list[Milestone]
    created_at: float
    target_revenue_usd: float = 0.0
    current_revenue_usd: float = 0.0

    @property
    def revenue_progress_pct(self) -> float:
        if self.target_revenue_usd <= 0:
            return 0.0
        return min(100.0, self.current_revenue_usd / self.target_revenue_usd * 100)

    def to_dict(self) -> dict:
        return {
            "obj_id": self.obj_id,
            "title": self.title,
            "horizon": self.horizon.value,
            "description": self.description,
            "milestones": [m.to_dict() for m in self.milestones],
            "created_at": self.created_at,
            "target_revenue_usd": self.target_revenue_usd,
            "current_revenue_usd": self.current_revenue_usd,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LongHorizonObjective:
        return cls(
            obj_id=d["obj_id"],
            title=d["title"],
            horizon=Horizon(d["horizon"]),
            description=d["description"],
            milestones=[Milestone.from_dict(m) for m in d.get("milestones", [])],
            created_at=d["created_at"],
            target_revenue_usd=d.get("target_revenue_usd", 0.0),
            current_revenue_usd=d.get("current_revenue_usd", 0.0),
        )


class ObjectiveManager:
    def __init__(self) -> None:
        self._objectives: dict[str, LongHorizonObjective] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _load(self) -> dict[str, LongHorizonObjective]:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_OBJECTIVES_KEY)
                if data and isinstance(data, dict):
                    self._objectives = {k: LongHorizonObjective.from_dict(v) for k, v in data.items()}
            except Exception:
                pass
            self._loaded = True
        return self._objectives

    async def _save(self, objectives: dict[str, LongHorizonObjective]) -> None:
        self._objectives = objectives
        try:
            cache = get_cache()
            await cache.set(_OBJECTIVES_KEY, {k: v.to_dict() for k, v in objectives.items()}, ttl_seconds=_OBJECTIVES_TTL)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add_objective(
        self,
        title: str,
        horizon: Horizon,
        description: str,
        target_revenue: float,
        milestones_data: list[dict],
    ) -> LongHorizonObjective:
        milestones = [
            Milestone(
                milestone_id=str(uuid.uuid4()),
                title=m.get("title", ""),
                target_date_ts=m.get("target_date_ts", time.time() + 86400 * 30),
                metric=m.get("metric", ""),
                target_value=m.get("target_value", 0.0),
            )
            for m in milestones_data
        ]
        obj = LongHorizonObjective(
            obj_id=str(uuid.uuid4()),
            title=title,
            horizon=horizon,
            description=description,
            milestones=milestones,
            created_at=time.time(),
            target_revenue_usd=target_revenue,
        )
        objectives = await self._load()
        objectives[obj.obj_id] = obj
        await self._save(objectives)
        return obj

    async def update_milestone(self, obj_id: str, milestone_id: str, current_value: float) -> Optional[Milestone]:
        objectives = await self._load()
        obj = objectives.get(obj_id)
        if not obj:
            return None
        for ms in obj.milestones:
            if ms.milestone_id == milestone_id:
                ms.current_value = current_value
                if current_value >= ms.target_value:
                    ms.status = MilestoneStatus.ACHIEVED
                elif time.time() > ms.target_date_ts and current_value < ms.target_value:
                    ms.status = MilestoneStatus.MISSED
                else:
                    ms.status = MilestoneStatus.IN_PROGRESS
                await self._save(objectives)
                return ms
        return None

    async def get_objectives(self, horizon_filter: Optional[Horizon] = None) -> list[LongHorizonObjective]:
        objectives = await self._load()
        result = list(objectives.values())
        if horizon_filter:
            result = [o for o in result if o.horizon == horizon_filter]
        return result

    async def revenue_summary(self) -> dict:
        objectives = await self._load()
        by_horizon: dict[str, dict] = {}
        on_track = 0
        at_risk = 0

        for obj in objectives.values():
            h = obj.horizon.value
            if h not in by_horizon:
                by_horizon[h] = {"target_usd": 0.0, "current_usd": 0.0, "count": 0}
            by_horizon[h]["target_usd"] += obj.target_revenue_usd
            by_horizon[h]["current_usd"] += obj.current_revenue_usd
            by_horizon[h]["count"] += 1
            if obj.revenue_progress_pct >= 70:
                on_track += 1
            else:
                at_risk += 1

        total_target = sum(v["target_usd"] for v in by_horizon.values())
        total_current = sum(v["current_usd"] for v in by_horizon.values())
        overall_pct = min(100.0, total_current / total_target * 100) if total_target > 0 else 0.0

        return {
            "by_horizon": by_horizon,
            "overall_progress_pct": overall_pct,
            "on_track_objectives": on_track,
            "at_risk_objectives": at_risk,
        }

    async def generate_objectives(self) -> list[LongHorizonObjective]:
        existing = await self._load()
        if existing:
            return list(existing.values())

        now = time.time()
        defaults = [
            {
                "title": "Q1 Revenue $10K",
                "horizon": Horizon.QUARTERLY,
                "description": "Reach $10,000 in revenue within the quarter across all channels",
                "target_revenue": 10_000.0,
                "milestones": [
                    {"title": "First $1K", "target_date_ts": now + 86400 * 14, "metric": "revenue_usd", "target_value": 1000},
                    {"title": "Mid-quarter $5K", "target_date_ts": now + 86400 * 45, "metric": "revenue_usd", "target_value": 5000},
                    {"title": "$10K achieved", "target_date_ts": now + 86400 * 90, "metric": "revenue_usd", "target_value": 10000},
                ],
            },
            {
                "title": "Monthly Content Calendar",
                "horizon": Horizon.MONTHLY,
                "description": "Publish a full month of content across all brand channels",
                "target_revenue": 0.0,
                "milestones": [
                    {"title": "Week 1 content live", "target_date_ts": now + 86400 * 7, "metric": "posts_published", "target_value": 7},
                    {"title": "Full month published", "target_date_ts": now + 86400 * 30, "metric": "posts_published", "target_value": 28},
                ],
            },
            {
                "title": "Weekly Growth Loops",
                "horizon": Horizon.WEEKLY,
                "description": "Execute at least 3 growth loops this week",
                "target_revenue": 0.0,
                "milestones": [
                    {"title": "Loop 1 complete", "target_date_ts": now + 86400 * 2, "metric": "loops_run", "target_value": 1},
                    {"title": "3 loops complete", "target_date_ts": now + 86400 * 7, "metric": "loops_run", "target_value": 3},
                ],
            },
            {
                "title": "Daily Shopify Optimization",
                "horizon": Horizon.DAILY,
                "description": "Complete daily Shopify store optimization tasks",
                "target_revenue": 0.0,
                "milestones": [
                    {"title": "Price optimization done", "target_date_ts": now + 86400, "metric": "tasks_complete", "target_value": 1},
                    {"title": "All daily tasks done", "target_date_ts": now + 86400, "metric": "tasks_complete", "target_value": 3},
                ],
            },
        ]

        created: list[LongHorizonObjective] = []
        for d in defaults:
            obj = await self.add_objective(
                title=d["title"],
                horizon=d["horizon"],
                description=d["description"],
                target_revenue=d["target_revenue"],
                milestones_data=d["milestones"],
            )
            created.append(obj)
        return created


_manager_instance: ObjectiveManager | None = None


def get_objective_manager() -> ObjectiveManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ObjectiveManager()
    return _manager_instance
