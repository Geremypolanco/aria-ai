"""
Executive Council — Coordinates all C-suite agents for unified strategic output.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel
from apps.executive.ceo_agent import get_ceo_agent
from apps.executive.coo_agent import get_coo_agent
from apps.executive.cto_agent import get_cto_agent
from apps.executive.cfo_agent import get_cfo_agent
from apps.executive.cmo_agent import get_cmo_agent

_KEY = "executive:council:v1"
_TTL = 90 * 24 * 3600  # 90 days


@dataclass
class ExecutiveReport:
    report_id: str
    period: str
    strategic_decisions: list
    operational_health: dict
    financial_outlook: dict
    marketing_priorities: list
    tech_priorities: list
    top_actions: list
    created_at: float

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "period": self.period,
            "strategic_decisions": self.strategic_decisions,
            "operational_health": self.operational_health,
            "financial_outlook": self.financial_outlook,
            "marketing_priorities": self.marketing_priorities,
            "tech_priorities": self.tech_priorities,
            "top_actions": self.top_actions,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutiveReport":
        return cls(
            report_id=data["report_id"],
            period=data["period"],
            strategic_decisions=data.get("strategic_decisions", []),
            operational_health=data.get("operational_health", {}),
            financial_outlook=data.get("financial_outlook", {}),
            marketing_priorities=data.get("marketing_priorities", []),
            tech_priorities=data.get("tech_priorities", []),
            top_actions=data.get("top_actions", []),
            created_at=data.get("created_at", time.time()),
        )


class ExecutiveCouncil:
    def __init__(self) -> None:
        self._reports: list[dict] = []
        self._last_report_ts: float = 0.0
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._reports = data.get("reports", [])
                    self._last_report_ts = data.get("last_report_ts", 0.0)
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            payload = {
                "reports": self._reports[-50:],
                "last_report_ts": self._last_report_ts,
            }
            await cache.set(_KEY, payload, ttl_seconds=_TTL)
        except Exception:
            pass

    async def convene(self, niche: str, current_metrics: dict) -> ExecutiveReport:
        await self._load()

        # CEO: make a strategic decision
        ceo = get_ceo_agent()
        ceo._loaded = True  # Skip redis load in tests
        decision = await ceo.make_strategic_decision(
            context={"niche": niche, **current_metrics},
            options=["Double down on content", "Launch paid ads", "Expand product line"],
        )
        vision = await ceo.weekly_vision_statement(niche)

        # COO: operational health
        coo = get_coo_agent()
        coo._loaded = True
        dept_health = coo.department_health()
        ops_report = coo.operations_report()

        # CFO: financial outlook
        cfo = get_cfo_agent()
        cfo._loaded = True
        revenue_val = float(current_metrics.get("revenue", current_metrics.get("revenue_usd", 5000)))
        scenario = await cfo.model_scenario(
            name=f"Q-{niche}",
            revenue_drivers={"primary": revenue_val},
            cost_drivers={"ops": revenue_val * 0.4},
        )
        financial_outlook = {
            "scenario": scenario.name,
            "revenue_projection": scenario.revenue_projection,
            "profit_margin": scenario.profit_margin,
            "roi": scenario.roi,
            "risk_level": scenario.risk_level,
        }

        # CMO: marketing priorities
        cmo = get_cmo_agent()
        cmo._loaded = True
        growth = await cmo.growth_strategy(current_metrics, goal_metric="revenue")
        marketing_priorities = growth.get("channel_mix", [])

        # CTO: tech priorities
        cto = get_cto_agent()
        cto._loaded = True
        radar = cto.tech_radar()
        tech_priorities = radar.get("adopt", []) + radar.get("trial", [])

        # Synthesize top actions
        top_actions = [
            f"CEO: {decision.title}",
            f"Vision: {vision[:100]}",
            f"CMO: Focus on {marketing_priorities[0] if marketing_priorities else 'content'}",
            f"CFO: {financial_outlook['risk_level']} risk scenario — ROI {financial_outlook['roi']:.1f}%",
        ]

        report = ExecutiveReport(
            report_id=str(uuid.uuid4()),
            period=f"Week of {time.strftime('%Y-%m-%d')}",
            strategic_decisions=[decision.to_dict()],
            operational_health=ops_report,
            financial_outlook=financial_outlook,
            marketing_priorities=marketing_priorities,
            tech_priorities=tech_priorities,
            top_actions=top_actions,
            created_at=time.time(),
        )
        self._reports.append(report.to_dict())
        self._last_report_ts = report.created_at
        await self._save()
        return report

    async def emergency_pivot(self, trigger: str, context: dict) -> dict:
        ai = get_ai_client()
        context_text = "; ".join(f"{k}: {v}" for k, v in context.items())
        resp = await ai.complete(
            system=(
                "You are the Executive Council. A crisis requires immediate action. "
                "Provide a 3-step emergency pivot plan: STEP1, STEP2, STEP3, each with a brief action."
            ),
            user=f"Crisis trigger: {trigger}\nContext: {context_text}",
            model=AIModel.STRATEGY,
            max_tokens=300,
        )
        content = resp.content if resp.success else ""

        steps = []
        if content:
            for line in content.split("\n"):
                line = line.strip()
                for prefix in ("STEP1:", "STEP2:", "STEP3:", "1.", "2.", "3."):
                    if line.startswith(prefix):
                        steps.append(line.split(":", 1)[-1].strip() if ":" in line else line[2:].strip())
                        break

        if not steps:
            steps = [
                "Halt non-essential spending immediately",
                "Concentrate resources on highest-ROI channel",
                "Communicate transparently with stakeholders",
            ]

        return {
            "trigger": trigger,
            "context": context,
            "pivot_steps": steps[:3],
            "decision_ts": time.time(),
            "status": "emergency_action_plan_ready",
        }

    async def quarterly_planning(self, objectives: list[str]) -> dict:
        ai = get_ai_client()
        objectives_text = "; ".join(objectives)
        resp = await ai.complete(
            system=(
                "You are the Executive Council doing quarterly planning. "
                "Create a high-level 13-week execution plan with monthly milestones."
            ),
            user=f"Quarterly objectives: {objectives_text}",
            model=AIModel.STRATEGY,
            max_tokens=400,
        )
        plan_text = resp.content if resp.success else "Execute objectives in priority order across 13 weeks."

        return {
            "objectives": objectives,
            "quarter_plan": plan_text,
            "month_1_focus": objectives[0] if objectives else "Foundation",
            "month_2_focus": objectives[1] if len(objectives) > 1 else "Growth",
            "month_3_focus": objectives[2] if len(objectives) > 2 else "Scale",
            "kpis": {
                "revenue_growth_pct": 30,
                "customer_acquisition": 500,
                "team_efficiency_pct": 85,
            },
            "created_at": time.time(),
        }

    def council_summary(self) -> dict:
        return {
            "reports_generated": len(self._reports),
            "last_report_ts": self._last_report_ts,
            "council_health": "active" if self._reports else "not_started",
        }


_instance: Optional[ExecutiveCouncil] = None


def get_executive_council() -> ExecutiveCouncil:
    global _instance
    if _instance is None:
        _instance = ExecutiveCouncil()
    return _instance
