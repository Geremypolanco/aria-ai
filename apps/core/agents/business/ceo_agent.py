"""
CEO Agent — Strategy, high-level decisions, and delegation to specialized agents.

The CEO Agent orchestrates the other agents, prioritizes business initiatives,
analyzes global metrics, and makes autonomous executive decisions.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent

logger = logging.getLogger("aria.business.ceo")


class CEOAgent(BaseAgent):
    IDENTITY = (
        "You are ARIA AI's CEO Agent. You think strategically like a Silicon Valley CEO. "
        "Your goal: maximize revenue, grow the brand, and keep operations autonomous. "
        "Delegate tasks to specialized agents. Make decisions based on real data."
    )

    def __init__(self) -> None:
        super().__init__(
            name="ceo",
            description="Executive strategy, high-level decisions, delegation, and business coordination",
            capabilities=["strategy", "planning", "delegation", "metrics", "decisions", "growth"],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mission = context.get("mission", "Analyze business status and propose an action plan")
        data = context.get("data", {})
        timeframe = context.get("timeframe", "next 2 weeks")

        # Gather current metrics
        metrics = await self._gather_business_metrics()

        # Strategic analysis with AI
        plan = await self.think(
            system=self.IDENTITY,
            user=(
                f"Mission: {mission}\n"
                f"Additional data: {data}\n"
                f"Timeframe: {timeframe}\n"
                f"Current metrics: {metrics}\n\n"
                f"Generate an executive plan with: "
                f"1) Current situation 2) 3 immediate priorities 3) KPIs to track "
                f"4) Delegation to specific agents 5) Concrete next steps."
            ),
        )

        # Identify which agents to activate
        agents_to_activate = self._identify_required_agents(plan, mission)

        return {
            "success": True,
            "agent": "ceo",
            "mission": mission,
            "strategic_plan": plan,
            "agents_to_activate": agents_to_activate,
            "metrics_snapshot": metrics,
            "summary": plan[:400] if plan else "Plan generated",
        }

    async def _gather_business_metrics(self) -> dict:
        """Gathers real business metrics from multiple sources."""
        metrics: dict = {}
        try:
            from apps.core.training.continuous_trainer import get_trainer

            status = get_trainer().get_status()
            metrics["system_cycle"] = status.get("cycle", 0)
            metrics["skills"] = status.get("skill_scores", {})
        except Exception:
            pass
        return metrics

    def _identify_required_agents(self, plan: str | None, mission: str) -> list[str]:
        """Identifies which specialized agents need to be activated."""
        # think() returns None when the AI client is unavailable/errors —
        # `plan + mission` would raise TypeError in exactly that case.
        plan_lower = ((plan or "") + mission).lower()
        agents = []
        if any(w in plan_lower for w in ["market", "seo", "content", "blog", "social"]):
            agents.append("marketing")
        if any(w in plan_lower for w in ["revenue", "sale", "stripe", "shopify", "product"]):
            agents.append("sales")
        if any(w in plan_lower for w in ["code", "deploy", "bug", "feature", "api", "app"]):
            agents.append("developer")
        if any(w in plan_lower for w in ["research", "analys", "trend", "competitor"]):
            agents.append("research")
        if any(w in plan_lower for w in ["email", "newsletter", "publish", "article"]):
            agents.append("content")
        if any(w in plan_lower for w in ["finance", "cost", "profit", "revenue", "expense"]):
            agents.append("finance")
        return agents or ["research"]
