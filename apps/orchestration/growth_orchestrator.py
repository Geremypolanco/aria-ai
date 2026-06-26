"""
GrowthOrchestrator — ARIA's central economic brain.

Aggregates signals from all subsystems, prioritizes highest-ROI actions,
allocates resources, and drives autonomous revenue growth cycles.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_KEY = "orchestration:growth:v1"
_TTL = 86400 * 90

_ACTION_TYPES = [
    "create_content",
    "run_ad",
    "optimize_product",
    "send_email",
    "run_sale",
    "build_quiz",
    "optimize_bundle",
    "retarget_campaign",
]


@dataclass
class GrowthAction:
    action_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    action_type: str = ""
    title: str = ""
    description: str = ""
    estimated_revenue_impact: float = 0.0
    estimated_effort_hours: float = 1.0
    roi_score: float = 0.0
    priority_rank: int = 0
    status: str = "queued"
    triggered_at: float = 0.0
    completed_at: float = 0.0
    actual_revenue: float = 0.0

    def __post_init__(self) -> None:
        if self.roi_score == 0.0 and self.estimated_effort_hours > 0:
            self.roi_score = round(
                self.estimated_revenue_impact / max(self.estimated_effort_hours, 0.1), 2
            )

    def effort_roi(self) -> float:
        return self.roi_score

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "title": self.title,
            "description": self.description,
            "estimated_revenue_impact": self.estimated_revenue_impact,
            "estimated_effort_hours": self.estimated_effort_hours,
            "roi_score": self.roi_score,
            "priority_rank": self.priority_rank,
            "status": self.status,
            "triggered_at": self.triggered_at,
            "completed_at": self.completed_at,
            "actual_revenue": self.actual_revenue,
        }


@dataclass
class WeeklyGrowthPlan:
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    week_start: str = ""
    actions: list = field(default_factory=list)
    total_estimated_revenue: float = 0.0
    total_effort_hours: float = 0.0
    strategic_focus: str = ""
    growth_objectives: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "week_start": self.week_start,
            "actions": [a.to_dict() if hasattr(a, "to_dict") else a for a in self.actions],
            "total_estimated_revenue": self.total_estimated_revenue,
            "total_effort_hours": self.total_effort_hours,
            "strategic_focus": self.strategic_focus,
            "growth_objectives": self.growth_objectives,
            "created_at": self.created_at,
        }


@dataclass
class EconomicSignals:
    revenue_7d: float = 0.0
    revenue_30d: float = 0.0
    conversion_rate: float = 0.02
    traffic_growth_pct: float = 0.0
    top_channel: str = "organic"
    weakest_channel: str = "paid"
    cash_runway_months: float = 6.0
    active_campaigns: int = 0
    content_pieces_this_week: int = 0
    leads_captured: int = 0


class GrowthOrchestrator:
    def __init__(self) -> None:
        self._actions: list[dict] = []
        self._plans: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._actions = data.get("actions", [])
                    self._plans = data.get("plans", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _KEY,
                {
                    "actions": self._actions[-500:],
                    "plans": self._plans[-50:],
                },
                ttl_seconds=_TTL,
            )
        except Exception:
            pass

    async def collect_economic_signals(self) -> EconomicSignals:
        signals = EconomicSignals()
        try:
            from apps.business.finance.cashflow_engine import get_cashflow_engine

            cf = get_cashflow_engine()
            signals.cash_runway_months = await cf.runway_months()
            monthly_list = await cf.monthly_summary()
            if isinstance(monthly_list, list) and monthly_list:
                signals.revenue_30d = monthly_list[0].get("total_income", 0.0)
            elif isinstance(monthly_list, dict):
                signals.revenue_30d = monthly_list.get("total_income", 0.0)
            signals.revenue_7d = signals.revenue_30d / 4
        except Exception:
            pass
        try:
            from apps.learning.economics.economic_learner import get_economic_learner

            report = await get_economic_learner().learning_report()
            best = report.get("best_channels", [])
            if best:
                signals.top_channel = best[0] if isinstance(best[0], str) else "organic"
        except Exception:
            pass
        try:
            from apps.learning.conversion.conversion_learner import get_conversion_learner

            forecast = await get_conversion_learner().conversion_forecast()
            signals.conversion_rate = forecast.get("predicted_cvr", 0.02)
        except Exception:
            pass
        try:
            from apps.autonomy.revenue_loops.revenue_loop_engine import get_revenue_loop_engine

            analytics = await get_revenue_loop_engine().loop_analytics()
            signals.active_campaigns = analytics.get("active_loops", 0)
        except Exception:
            pass
        return signals

    async def generate_growth_actions(
        self, signals: EconomicSignals, niche: str = "general"
    ) -> list[GrowthAction]:
        actions: list[GrowthAction] = []

        # Content actions (always needed)
        actions.append(
            GrowthAction(
                action_type="create_content",
                title=f"Write 3 SEO blog posts for '{niche}'",
                description="Target buyer-intent keywords with 800+ word posts",
                estimated_revenue_impact=500.0,
                estimated_effort_hours=6.0,
            )
        )
        actions.append(
            GrowthAction(
                action_type="optimize_product",
                title="Rewrite top 5 product descriptions",
                description="AI-optimize for conversion using benefit-led copy",
                estimated_revenue_impact=300.0,
                estimated_effort_hours=2.0,
            )
        )

        # Lead capture if low
        if signals.leads_captured < 10:
            actions.append(
                GrowthAction(
                    action_type="build_quiz",
                    title=f"Launch product recommendation quiz for {niche}",
                    description="5-question quiz for audience segmentation and email capture",
                    estimated_revenue_impact=800.0,
                    estimated_effort_hours=3.0,
                )
            )

        # Email action
        actions.append(
            GrowthAction(
                action_type="send_email",
                title="Send weekly value email to list",
                description="Nurture leads with educational content + soft CTA",
                estimated_revenue_impact=200.0,
                estimated_effort_hours=1.0,
            )
        )

        # Sales/revenue actions
        if signals.revenue_7d < 500 or signals.conversion_rate < 0.02:
            actions.append(
                GrowthAction(
                    action_type="run_sale",
                    title="24h flash sale — 20% off bestsellers",
                    description="Drive urgency with time-limited discount",
                    estimated_revenue_impact=1200.0,
                    estimated_effort_hours=1.0,
                )
            )

        # Ad action
        actions.append(
            GrowthAction(
                action_type="run_ad",
                title="Launch cart abandonment retargeting campaign",
                description="Target visitors who viewed products but didn't buy",
                estimated_revenue_impact=600.0,
                estimated_effort_hours=2.0,
            )
        )
        actions.append(
            GrowthAction(
                action_type="optimize_bundle",
                title="Create 3 product bundles with 15% savings",
                description="Increase AOV with complementary product combinations",
                estimated_revenue_impact=400.0,
                estimated_effort_hours=1.5,
            )
        )

        # Use AI to generate strategic action if available
        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system="You are a growth strategist. Be specific and concise.",
                user=(
                    f"Given: revenue_7d=${signals.revenue_7d:.0f}, "
                    f"conversion_rate={signals.conversion_rate:.1%}, "
                    f"niche={niche}. "
                    f"Suggest ONE high-impact growth action in this format: "
                    f"ACTION_TYPE: [type] | TITLE: [title] | IMPACT: [USD] | HOURS: [h]"
                ),
                model=AIModel.STRATEGY,
                max_tokens=100,
            )
            if resp.success and resp.content:
                parts = resp.content.split("|")
                if len(parts) >= 4:
                    atype = parts[0].replace("ACTION_TYPE:", "").strip().lower().replace(" ", "_")
                    title = parts[1].replace("TITLE:", "").strip()
                    try:
                        impact = float(
                            parts[2]
                            .replace("IMPACT:", "")
                            .replace("$", "")
                            .replace("USD", "")
                            .strip()
                        )
                    except ValueError:
                        impact = 300.0
                    try:
                        hours = float(parts[3].replace("HOURS:", "").replace("h", "").strip())
                    except ValueError:
                        hours = 2.0
                    if title:
                        actions.append(
                            GrowthAction(
                                action_type=atype or "create_content",
                                title=title,
                                description="AI-recommended strategic action",
                                estimated_revenue_impact=impact,
                                estimated_effort_hours=hours,
                            )
                        )
        except Exception:
            pass

        # Recalculate ROI scores and rank
        for a in actions:
            if a.roi_score == 0.0:
                a.roi_score = round(
                    a.estimated_revenue_impact / max(a.estimated_effort_hours, 0.1), 2
                )
        actions.sort(key=lambda a: a.roi_score, reverse=True)
        for i, a in enumerate(actions):
            a.priority_rank = i + 1
        return actions

    async def create_weekly_plan(self, niche: str = "general") -> WeeklyGrowthPlan:
        await self._load()
        import datetime

        signals = await self.collect_economic_signals()
        actions = await self.generate_growth_actions(signals, niche)

        # Select top actions within 40-hour budget
        selected: list[GrowthAction] = []
        total_hours = 0.0
        for a in actions:
            if total_hours + a.estimated_effort_hours <= 40.0:
                selected.append(a)
                total_hours += a.estimated_effort_hours

        strategic_focus = "Content-led growth with conversion optimization"
        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system="You are a growth strategist. Be concise.",
                user=f"In one sentence, what's the strategic focus for a {niche} business with {len(selected)} growth actions this week?",
                model=AIModel.FAST,
                max_tokens=60,
            )
            if resp.success and resp.content:
                strategic_focus = resp.content.strip()
        except Exception:
            pass

        plan = WeeklyGrowthPlan(
            week_start=datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            actions=selected,
            total_estimated_revenue=sum(a.estimated_revenue_impact for a in selected),
            total_effort_hours=total_hours,
            strategic_focus=strategic_focus,
            growth_objectives=[
                f"Generate ${sum(a.estimated_revenue_impact for a in selected):.0f} in revenue",
                "Capture 50+ email leads",
                f"Improve conversion rate above {signals.conversion_rate:.1%}",
            ],
        )
        self._plans.append(plan.to_dict())
        for a in selected:
            self._actions.append(a.to_dict())
        await self._save()
        return plan

    async def execute_next_action(self) -> GrowthAction | None:
        await self._load()
        for i, a in enumerate(self._actions):
            if a.get("status") == "queued":
                self._actions[i]["status"] = "running"
                self._actions[i]["triggered_at"] = time.time()
                await self._save()
                return GrowthAction(
                    **{k: v for k, v in a.items() if k in GrowthAction.__dataclass_fields__}
                )
        return None

    async def mark_action_complete(self, action_id: str, revenue_generated: float = 0.0) -> bool:
        await self._load()
        for i, a in enumerate(self._actions):
            if a.get("action_id") == action_id:
                self._actions[i]["status"] = "done"
                self._actions[i]["completed_at"] = time.time()
                self._actions[i]["actual_revenue"] = revenue_generated
                await self._save()
                return True
        return False

    async def autonomous_growth_cycle(self, niche: str = "general") -> dict:
        signals = await self.collect_economic_signals()
        actions = await self.generate_growth_actions(signals, niche)
        top_3 = actions[:3]
        return {
            "signals": {
                "revenue_7d": signals.revenue_7d,
                "conversion_rate": signals.conversion_rate,
                "leads_captured": signals.leads_captured,
                "top_channel": signals.top_channel,
            },
            "top_actions": [a.to_dict() for a in top_3],
            "priority_focus": top_3[0].title if top_3 else "Build content",
            "estimated_weekly_revenue": sum(a.estimated_revenue_impact for a in top_3),
            "total_actions_identified": len(actions),
        }

    def growth_analytics(self) -> dict:
        completed = [a for a in self._actions if a.get("status") == "done"]
        queued = [a for a in self._actions if a.get("status") == "queued"]
        roi_scores = [a.get("roi_score", 0) for a in self._actions if a.get("roi_score")]
        return {
            "total_actions_queued": len(queued),
            "completed": len(completed),
            "total_actual_revenue": sum(a.get("actual_revenue", 0) for a in completed),
            "avg_roi_score": round(sum(roi_scores) / len(roi_scores), 2) if roi_scores else 0.0,
            "current_plan_id": self._plans[-1]["plan_id"] if self._plans else None,
        }

    async def strategic_report(self, period: str = "week") -> dict:
        signals = await self.collect_economic_signals()
        analytics = self.growth_analytics()
        risk_factors = []
        if signals.cash_runway_months < 3:
            risk_factors.append("Low cash runway — prioritize revenue actions")
        if signals.conversion_rate < 0.01:
            risk_factors.append("Conversion rate below 1% — funnel optimization critical")
        if signals.leads_captured < 5:
            risk_factors.append("Low lead capture — add quiz/popup immediately")
        return {
            "period": period,
            "revenue_trend": "up" if signals.revenue_7d > 0 else "flat",
            "top_opportunity": "Launch quiz funnel for email capture + segmentation",
            "recommended_focus": (
                "Content + conversion" if signals.conversion_rate < 0.02 else "Scale paid ads"
            ),
            "risk_factors": risk_factors or ["None identified"],
            "next_steps": [
                "Create weekly content calendar",
                "Set up email automation sequences",
                "Launch retargeting for cart abandoners",
            ],
            "analytics": analytics,
        }


_instance: GrowthOrchestrator | None = None


def get_growth_orchestrator() -> GrowthOrchestrator:
    global _instance
    if _instance is None:
        _instance = GrowthOrchestrator()
    return _instance
