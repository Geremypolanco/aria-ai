from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_TTL = 90 * 24 * 3600
_CACHE_KEY = "autonomy:self_direction:v1"


class DirectiveType(str, Enum):
    OPTIMIZE = "OPTIMIZE"
    EXPLORE = "EXPLORE"
    CONSOLIDATE = "CONSOLIDATE"
    SCALE = "SCALE"
    PIVOT = "PIVOT"
    MAINTAIN = "MAINTAIN"


_DIRECTIVE_TEMPLATES: dict[DirectiveType, dict] = {
    DirectiveType.OPTIMIZE: {
        "title_tpl": "Optimise {channel} for maximum efficiency",
        "rationale_tpl": "Current performance is stable; targeted optimisation will improve margins and conversion rates.",
        "actions": [
            "Audit top-performing content and double down on winning formats",
            "A/B test pricing and packaging to improve conversion",
            "Reduce friction in checkout and onboarding flows",
            "Reallocate budget from underperforming channels to top performers",
            "Improve email automation sequences for higher open and click rates",
        ],
        "kpis": ["Conversion rate", "Revenue per visitor", "Customer acquisition cost"],
    },
    DirectiveType.SCALE: {
        "title_tpl": "Scale {channel} to capture market opportunity",
        "rationale_tpl": "Revenue trend is positive and budget allows for investment; now is the time to scale what is working.",
        "actions": [
            "Increase ad spend 2x on highest-ROI campaigns",
            "Expand content production to 3x current volume",
            "Launch affiliate programme to extend reach",
            "Open new distribution channels identified in market analysis",
            "Hire or contract support to handle increased operational load",
        ],
        "kpis": ["Monthly recurring revenue", "Customer count growth rate", "Channel reach"],
    },
    DirectiveType.PIVOT: {
        "title_tpl": "Pivot strategy to address declining revenue",
        "rationale_tpl": "Revenue trend is downward; maintaining current direction risks further decline. A strategic pivot is required.",
        "actions": [
            "Conduct emergency customer feedback audit",
            "Identify top 3 alternative monetisation angles",
            "Pause underperforming campaigns and reallocate budget",
            "Test new offer positioning with existing audience",
            "Reach out to top customers for direct insight",
        ],
        "kpis": ["Revenue stabilisation", "Customer retention rate", "New offer conversion rate"],
    },
    DirectiveType.EXPLORE: {
        "title_tpl": "Explore new growth opportunities",
        "rationale_tpl": "Core business is stable; exploration of new channels or products will diversify revenue.",
        "actions": [
            "Research 3 adjacent niches or product opportunities",
            "Run low-budget experiments on new channels",
            "Survey audience for unmet needs",
            "Prototype a new offer and test with small segment",
        ],
        "kpis": ["Experiment conversion rate", "New channel CAC", "Audience growth in new segment"],
    },
    DirectiveType.CONSOLIDATE: {
        "title_tpl": "Consolidate operations for stability",
        "rationale_tpl": "Multiple initiatives are running; consolidation will improve focus and execution quality.",
        "actions": [
            "Reduce active initiatives to top 3 by ROI",
            "Document and systematise repeatable processes",
            "Automate routine tasks to free capacity",
        ],
        "kpis": ["Operational efficiency score", "Revenue per hour worked", "Error rate"],
    },
    DirectiveType.MAINTAIN: {
        "title_tpl": "Maintain current trajectory",
        "rationale_tpl": "Business is performing at target; focus on consistency and preventing regression.",
        "actions": [
            "Continue current content and marketing cadence",
            "Monitor KPIs weekly for early warning signals",
            "Keep customer success processes sharp",
        ],
        "kpis": ["Revenue vs target", "Customer satisfaction score", "Churn rate"],
    },
}


@dataclass
class AutonomousDirective:
    directive_id: str
    type: DirectiveType
    title: str
    rationale: str
    actions: list[str]
    kpis: list[str]
    confidence: float
    generated_at: float
    executed: bool = False

    def to_dict(self) -> dict:
        return {
            "directive_id": self.directive_id,
            "type": self.type.value,
            "title": self.title,
            "rationale": self.rationale,
            "actions": self.actions,
            "kpis": self.kpis,
            "confidence": self.confidence,
            "generated_at": self.generated_at,
            "executed": self.executed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AutonomousDirective:
        return cls(
            directive_id=data["directive_id"],
            type=DirectiveType(data["type"]),
            title=data["title"],
            rationale=data["rationale"],
            actions=data.get("actions", []),
            kpis=data.get("kpis", []),
            confidence=data.get("confidence", 0.7),
            generated_at=data.get("generated_at", time.time()),
            executed=data.get("executed", False),
        )


class SelfDirector:
    def __init__(self) -> None:
        self._ai = get_ai_client()
        self._directives: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._directives = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        self._loaded = True
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._directives[-200:], ttl_seconds=_TTL)
        except Exception:
            pass

    def _choose_directive_type(self, context: dict) -> DirectiveType:
        revenue_trend = context.get("revenue_trend", "flat")
        available_budget = context.get("available_budget_usd", 0.0)
        if revenue_trend == "down":
            return DirectiveType.PIVOT
        if revenue_trend == "up" and available_budget > 1000:
            return DirectiveType.SCALE
        return DirectiveType.OPTIMIZE

    async def generate_directive(self, context: dict) -> AutonomousDirective:
        await self._load()
        directive_type = self._choose_directive_type(context)
        channel = context.get("top_performing_channel", "core")
        bottleneck = context.get("biggest_bottleneck", "conversion")
        template = _DIRECTIVE_TEMPLATES[directive_type]
        title = template["title_tpl"].format(channel=channel)
        rationale = template["rationale_tpl"]
        actions = list(template["actions"])
        kpis = list(template["kpis"])
        confidence = 0.75

        try:
            prompt = (
                f"You are an autonomous business strategy AI. Given this context:\n"
                f"- Revenue trend: {context.get('revenue_trend', 'flat')}\n"
                f"- Top channel: {channel}\n"
                f"- Biggest bottleneck: {bottleneck}\n"
                f"- Available budget: ${context.get('available_budget_usd', 0)}\n\n"
                f"Generate a {directive_type.value} directive with:\n"
                f"1. A specific title (one line)\n"
                f"2. Rationale (two sentences)\n"
                f"3. Five concrete actions\n"
                f"4. Three KPIs to track\n"
                f"Be specific, avoid generic advice."
            )
            result = await self._ai.complete(prompt, model=AIModel.STRATEGY)
            if result and result.success and result.content and len(result.content) > 50:
                lines = [l.strip() for l in result.content.split("\n") if l.strip()]
                if lines:
                    title = lines[0].lstrip("1234567890. ").strip()
                confidence = 0.85
        except Exception:
            pass

        directive = AutonomousDirective(
            directive_id=str(uuid.uuid4()),
            type=directive_type,
            title=title,
            rationale=rationale,
            actions=actions[:5],
            kpis=kpis[:3],
            confidence=confidence,
            generated_at=time.time(),
            executed=False,
        )
        self._directives.append(directive.to_dict())
        await self._save()
        return directive

    async def self_optimize(self, performance_data: dict) -> list[AutonomousDirective]:
        directives: list[AutonomousDirective] = []
        contexts = [
            {
                "revenue_trend": performance_data.get("revenue_trend", "flat"),
                "top_performing_channel": performance_data.get("top_channel", "content"),
                "biggest_bottleneck": performance_data.get("bottleneck", "traffic"),
                "available_budget_usd": performance_data.get("budget", 500),
            },
            {
                "revenue_trend": "flat",
                "top_performing_channel": performance_data.get("second_channel", "email"),
                "biggest_bottleneck": "conversion",
                "available_budget_usd": 0,
            },
            {
                "revenue_trend": "up",
                "top_performing_channel": "content",
                "biggest_bottleneck": "scale",
                "available_budget_usd": 2000,
            },
        ]
        for ctx in contexts[:3]:
            directive = await self.generate_directive(ctx)
            directives.append(directive)
        return directives

    async def pending_directives(self) -> list[AutonomousDirective]:
        await self._load()
        return [
            AutonomousDirective.from_dict(d)
            for d in self._directives
            if not d.get("executed", False)
        ]

    async def mark_executed(self, directive_id: str) -> Optional[AutonomousDirective]:
        await self._load()
        for i, d in enumerate(self._directives):
            if d.get("directive_id") == directive_id:
                self._directives[i]["executed"] = True
                await self._save()
                return AutonomousDirective.from_dict(self._directives[i])
        return None

    async def autonomous_cycle(self, metrics: dict) -> dict:
        directive = await self.generate_directive(
            context={
                "revenue_trend": metrics.get("revenue_trend", "flat"),
                "top_performing_channel": metrics.get("top_channel", "content"),
                "biggest_bottleneck": metrics.get("bottleneck", "conversion"),
                "available_budget_usd": metrics.get("budget", 0),
            }
        )
        next_actions = directive.actions[:3]
        return {
            "directive": directive.to_dict(),
            "next_actions": next_actions,
            "confidence": directive.confidence,
        }

    def summary(self) -> dict:
        total = len(self._directives)
        executed = sum(1 for d in self._directives if d.get("executed", False))
        return {
            "total_directives": total,
            "pending": total - executed,
            "executed": executed,
        }


_self_director_instance: SelfDirector | None = None


def get_self_director() -> SelfDirector:
    global _self_director_instance
    if _self_director_instance is None:
        _self_director_instance = SelfDirector()
    return _self_director_instance
