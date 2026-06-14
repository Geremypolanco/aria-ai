from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache

_CACHE_KEY = "strategy:priority:v1"
_CACHE_TTL = 86400 * 30  # 30 days


@dataclass
class StrategyAction:
    action_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    category: str = "content"  # content|paid_acquisition|seo|product|retention|partnership
    estimated_roi: float = 0.0
    effort_score: float = 5.0  # 0-10, higher = more effort
    time_to_result_days: int = 30
    leverage_score: float = 0.5  # 0-1
    compounding: bool = False
    dependencies: list[str] = field(default_factory=list)
    priority_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "estimated_roi": self.estimated_roi,
            "effort_score": self.effort_score,
            "time_to_result_days": self.time_to_result_days,
            "leverage_score": self.leverage_score,
            "compounding": self.compounding,
            "dependencies": self.dependencies,
            "priority_score": self.priority_score,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StrategyAction:
        return cls(
            action_id=d.get("action_id", str(uuid.uuid4())),
            title=d.get("title", ""),
            description=d.get("description", ""),
            category=d.get("category", "content"),
            estimated_roi=d.get("estimated_roi", 0.0),
            effort_score=d.get("effort_score", 5.0),
            time_to_result_days=d.get("time_to_result_days", 30),
            leverage_score=d.get("leverage_score", 0.5),
            compounding=d.get("compounding", False),
            dependencies=d.get("dependencies", []),
            priority_score=d.get("priority_score", 0.0),
        )


class PriorityEngine:
    def __init__(self) -> None:
        self._actions: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._actions = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._actions, ttl_seconds=_CACHE_TTL)
        except Exception:
            pass

    def _score(self, action: StrategyAction) -> float:
        """
        priority_score = (roi * 0.35) + (leverage * 0.30) + ((10 - effort) * 0.02)
                        + (0.10 if compounding else 0)
                        + (max(0, 30 - time_to_result_days) / 30 * 0.15)
        Capped at 0-100.
        """
        roi_component = action.estimated_roi * 0.35
        leverage_component = action.leverage_score * 0.30
        effort_component = (10.0 - action.effort_score) * 0.02
        compounding_component = 0.10 if action.compounding else 0.0
        speed_component = (
            max(0.0, 30.0 - action.time_to_result_days) / 30.0 * 0.15
        )
        raw = roi_component + leverage_component + effort_component + compounding_component + speed_component
        return max(0.0, min(100.0, raw))

    async def add_action(self, action: StrategyAction) -> StrategyAction:
        await self._load()
        action.priority_score = self._score(action)
        self._actions.append(action.to_dict())
        await self._save()
        return action

    async def rank_actions(
        self, actions: Optional[list[StrategyAction]] = None
    ) -> list[StrategyAction]:
        if actions is None:
            await self._load()
            actions = [StrategyAction.from_dict(d) for d in self._actions]

        for a in actions:
            a.priority_score = self._score(a)

        return sorted(actions, key=lambda a: a.priority_score, reverse=True)

    async def top_priorities(self, limit: int = 5) -> list[StrategyAction]:
        ranked = await self.rank_actions()
        return ranked[:limit]

    async def allocate_resources(
        self, total_hours: int, total_budget_usd: float
    ) -> dict:
        top = await self.top_priorities(limit=10)
        if not top:
            return {"allocations": [], "total_hours": total_hours, "total_budget_usd": total_budget_usd}

        total_score = sum(a.priority_score for a in top)
        allocations = []
        for action in top:
            share = action.priority_score / total_score if total_score > 0 else 1.0 / len(top)
            allocations.append({
                "action_id": action.action_id,
                "title": action.title,
                "priority_score": action.priority_score,
                "allocated_hours": round(total_hours * share, 1),
                "allocated_budget_usd": round(total_budget_usd * share, 2),
            })

        return {
            "allocations": allocations,
            "total_hours": total_hours,
            "total_budget_usd": total_budget_usd,
        }

    async def quick_wins(self) -> list[StrategyAction]:
        await self._load()
        actions = [StrategyAction.from_dict(d) for d in self._actions]
        wins = [
            a for a in actions
            if a.effort_score <= 3 and a.time_to_result_days <= 14
        ]
        return sorted(wins, key=lambda a: self._score(a), reverse=True)

    async def compounding_actions(self) -> list[StrategyAction]:
        await self._load()
        actions = [StrategyAction.from_dict(d) for d in self._actions]
        compounding = [a for a in actions if a.compounding]
        return sorted(compounding, key=lambda a: a.leverage_score, reverse=True)

    def summary(self) -> dict:
        if not self._actions:
            return {
                "total_actions": 0,
                "avg_priority_score": 0.0,
                "quick_wins": 0,
                "compounding_count": 0,
            }

        actions = [StrategyAction.from_dict(d) for d in self._actions]
        scored = [self._score(a) for a in actions]
        avg_score = sum(scored) / len(scored)
        quick_wins = sum(
            1 for a in actions
            if a.effort_score <= 3 and a.time_to_result_days <= 14
        )
        compounding_count = sum(1 for a in actions if a.compounding)

        return {
            "total_actions": len(actions),
            "avg_priority_score": round(avg_score, 4),
            "quick_wins": quick_wins,
            "compounding_count": compounding_count,
        }


_engine_instance: Optional[PriorityEngine] = None


def get_priority_engine() -> PriorityEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PriorityEngine()
    return _engine_instance
