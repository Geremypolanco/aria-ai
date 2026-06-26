"""
ARIA Strategic Planner — Long-horizon goal decomposition (days–weeks–months).

The 3 planning layers:
  Strategic (this file): "What should ARIA pursue over the next month?"
    - Operates on GOALS, not tasks
    - Reasons about resource constraints, opportunity cost, risk appetite
    - Output: ordered list of strategic objectives with rationale

  Tactical (tactical_planner.py): "What will ARIA do this week to advance a strategic goal?"
    - Decomposes strategic objectives into tactical campaigns
    - Assigns priorities and rough timelines

  Execution (execution_planner.py): "What exact actions happen today?"
    - Breaks tactical campaigns into specific tool calls
    - Manages dependencies and parallelism

Design:
  - Strategic planner consults the world model to understand current state
  - Strategic planner consults the hypothesis engine to evaluate options
  - Output feeds directly into the tactical planner
  - All decisions are logged with reasoning for audit and learning
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger("aria.planning.strategic")

HORIZON_DAYS = 30
MAX_OBJECTIVES = 5


class StrategicPriority(StrEnum):
    CRITICAL = "critical"  # existential — must execute
    HIGH = "high"  # significant ROI
    MEDIUM = "medium"  # worthwhile but deferrable
    LOW = "low"  # nice to have


@dataclass
class StrategicObjective:
    id: str
    title: str
    rationale: str  # WHY this objective matters
    success_criteria: list[str]  # how we know it's achieved
    priority: StrategicPriority
    estimated_effort_days: float
    estimated_revenue_impact: float  # USD, can be 0 for foundational work
    risk_level: float  # 0.0–1.0
    dependencies: list[str]  # other objective IDs that must precede this
    horizon_days: int = HORIZON_DAYS
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["priority"] = self.priority.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> StrategicObjective:
        d = dict(d)
        d["priority"] = StrategicPriority(d.get("priority", "medium"))
        return cls(**d)

    def roi_score(self) -> float:
        """Revenue per day-of-effort, adjusted for risk."""
        effort = max(0.1, self.estimated_effort_days)
        raw_roi = self.estimated_revenue_impact / effort
        return raw_roi * (1.0 - self.risk_level * 0.5)


@dataclass
class StrategicPlan:
    id: str
    context_summary: str  # what ARIA knows about the current situation
    objectives: list[StrategicObjective]
    reasoning: str  # LLM chain-of-thought for this plan
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "context_summary": self.context_summary,
            "objectives": [o.to_dict() for o in self.objectives],
            "reasoning": self.reasoning,
            "created_at": self.created_at,
            "total_estimated_days": sum(o.estimated_effort_days for o in self.objectives),
            "total_revenue_potential": sum(o.estimated_revenue_impact for o in self.objectives),
        }

    def top_priority(self) -> StrategicObjective | None:
        critical = [o for o in self.objectives if o.priority == StrategicPriority.CRITICAL]
        if critical:
            return max(critical, key=lambda o: o.roi_score())
        high = [o for o in self.objectives if o.priority == StrategicPriority.HIGH]
        if high:
            return max(high, key=lambda o: o.roi_score())
        return max(self.objectives, key=lambda o: o.roi_score()) if self.objectives else None


class StrategicPlanner:
    """
    Long-horizon strategic planner for ARIA.

    Builds a strategic plan by:
    1. Assessing current state (world model + metrics)
    2. Identifying opportunities (hypothesis engine)
    3. Scoring and ranking objectives (ROI, risk, effort)
    4. Outputting ordered strategic priorities

    Usage:
        planner = StrategicPlanner(ai_client)
        plan = await planner.plan(
            owner_goals=["generate $500/month passive income"],
            constraints={"time_budget_hours_per_week": 5},
        )
        print(plan.top_priority().title)
    """

    def __init__(self, ai_client=None) -> None:
        self._ai = ai_client

    def set_ai_client(self, ai_client) -> None:
        self._ai = ai_client

    async def plan(
        self,
        owner_goals: list[str],
        constraints: dict[str, Any] | None = None,
        current_metrics: dict[str, Any] | None = None,
    ) -> StrategicPlan:
        constraints = constraints or {}
        current_metrics = current_metrics or {}
        plan_id = uuid.uuid4().hex[:8]

        context_summary = self._build_context_summary(owner_goals, constraints, current_metrics)

        reasoning, objectives = await self._generate_objectives(
            owner_goals, constraints, current_metrics, context_summary
        )

        plan = StrategicPlan(
            id=plan_id,
            context_summary=context_summary,
            objectives=objectives,
            reasoning=reasoning,
        )

        await self._persist(plan)
        logger.info(
            "[Strategic] Plan %s: %d objectives, top=%s",
            plan_id,
            len(objectives),
            plan.top_priority().title if plan.top_priority() else "none",
        )
        return plan

    def _build_context_summary(self, goals: list[str], constraints: dict, metrics: dict) -> str:
        lines = [
            f"Owner goals: {'; '.join(goals)}",
            f"Constraints: {json.dumps(constraints)}",
            f"Current metrics: {json.dumps(metrics)}",
        ]
        return "\n".join(lines)

    async def _generate_objectives(
        self,
        goals: list[str],
        constraints: dict,
        metrics: dict,
        context: str,
    ) -> tuple[str, list[StrategicObjective]]:
        if not self._ai:
            return self._fallback_objectives(goals)

        system = (
            "You are ARIA's strategic planning engine. Generate concrete strategic objectives.\n\n"
            "Each objective must be:\n"
            "  - Specific and measurable\n"
            "  - Achievable within the time horizon\n"
            "  - Ordered by ROI (revenue per day-of-effort)\n"
            "  - Grounded in the owner's actual constraints\n\n"
            "Return JSON:\n"
            "{\n"
            '  "reasoning": "<strategic analysis>",\n'
            '  "objectives": [\n'
            "    {\n"
            '      "title": "<objective>",\n'
            '      "rationale": "<why this matters>",\n'
            '      "success_criteria": ["<criterion 1>", "<criterion 2>"],\n'
            '      "priority": "critical|high|medium|low",\n'
            '      "estimated_effort_days": 3.5,\n'
            '      "estimated_revenue_impact": 200.0,\n'
            '      "risk_level": 0.3,\n'
            '      "dependencies": []\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"Generate {MAX_OBJECTIVES} objectives max. "
            "Risk level: 0=safe, 1=highly risky. "
            "Be conservative with revenue estimates."
        )
        user_msg = (
            f"Strategic context:\n{context}\n\n"
            f"Owner goals: {goals}\n"
            f"Constraints: {json.dumps(constraints)}\n"
            f"Current performance: {json.dumps(metrics)}"
        )

        try:
            raw = await self._ai.complete_json(system=system, user=user_msg)
            reasoning = raw.get("reasoning", "")
            raw_objs = raw.get("objectives", [])[:MAX_OBJECTIVES]

            objectives = []
            all_ids = [f"obj_{i}" for i in range(len(raw_objs))]
            for i, ro in enumerate(raw_objs):
                dep_indices = ro.get("dependencies", [])
                dep_ids = [all_ids[j] for j in dep_indices if isinstance(j, int) and j < i]
                objectives.append(
                    StrategicObjective(
                        id=all_ids[i],
                        title=ro.get("title", f"Objective {i}"),
                        rationale=ro.get("rationale", ""),
                        success_criteria=ro.get("success_criteria", []),
                        priority=StrategicPriority(ro.get("priority", "medium")),
                        estimated_effort_days=float(ro.get("estimated_effort_days", 7)),
                        estimated_revenue_impact=float(ro.get("estimated_revenue_impact", 0)),
                        risk_level=float(ro.get("risk_level", 0.5)),
                        dependencies=dep_ids,
                    )
                )
            return reasoning, objectives

        except Exception as exc:
            logger.warning("[Strategic] LLM generation failed: %s", exc)
            return self._fallback_objectives(goals)

    def _fallback_objectives(self, goals: list[str]) -> tuple[str, list[StrategicObjective]]:
        return (
            "Fallback: AI unavailable for strategic analysis.",
            [
                StrategicObjective(
                    id="obj_0",
                    title=goal[:100],
                    rationale="User-specified goal",
                    success_criteria=["Goal achieved"],
                    priority=StrategicPriority.HIGH,
                    estimated_effort_days=7.0,
                    estimated_revenue_impact=0.0,
                    risk_level=0.3,
                    dependencies=[],
                )
                for goal in goals[:MAX_OBJECTIVES]
            ],
        )

    async def _persist(self, plan: StrategicPlan) -> None:
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if cache:
                await cache.set(
                    f"aria:planning:strategic:{plan.id}",
                    json.dumps(plan.to_dict()),
                    ttl_seconds=86400 * 30,
                )
                # Also store as current plan
                await cache.set(
                    "aria:planning:strategic:current",
                    json.dumps(plan.to_dict()),
                    ttl_seconds=86400 * 30,
                )
        except Exception as exc:
            logger.debug("[Strategic] Persist failed: %s", exc)

    async def load_current(self) -> StrategicPlan | None:
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if cache:
                raw = await cache.get("aria:planning:strategic:current")
                if raw:
                    d = json.loads(raw)
                    objectives = [StrategicObjective.from_dict(o) for o in d.get("objectives", [])]
                    return StrategicPlan(
                        id=d["id"],
                        context_summary=d["context_summary"],
                        objectives=objectives,
                        reasoning=d["reasoning"],
                        created_at=d["created_at"],
                    )
        except Exception as exc:
            logger.debug("[Strategic] Load failed: %s", exc)
        return None


_planner: StrategicPlanner | None = None


def get_strategic_planner(ai_client=None) -> StrategicPlanner:
    global _planner
    if _planner is None:
        _planner = StrategicPlanner(ai_client)
    elif ai_client is not None and _planner._ai is None:
        _planner.set_ai_client(ai_client)
    return _planner
