"""
Revenue optimization — identifies quick wins and builds growth scenarios.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.memory.redis_client import get_cache

_OPTIMIZER_KEY = "revenue:optimizer:v1"
_OPTIMIZER_TTL = 86400 * 30


class ActionType(str, Enum):
    PRICE_INCREASE = "price_increase"
    BUNDLE_OFFER = "bundle_offer"
    UPSELL = "upsell"
    CROSS_SELL = "cross_sell"
    WIN_BACK_CAMPAIGN = "win_back_campaign"
    CHANNEL_SHIFT = "channel_shift"
    COST_REDUCTION = "cost_reduction"
    CONVERSION_LIFT = "conversion_lift"


@dataclass
class OptimizationAction:
    action_id: str
    action_type: ActionType
    title: str
    description: str
    estimated_revenue_lift_usd: float
    effort_days: int
    confidence: float
    priority: int = 1

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type.value,
            "title": self.title,
            "description": self.description,
            "estimated_revenue_lift_usd": round(self.estimated_revenue_lift_usd, 2),
            "effort_days": self.effort_days,
            "confidence": round(self.confidence, 3),
            "priority": self.priority,
        }


@dataclass
class RevenueScenario:
    name: str
    monthly_revenue_usd: float
    growth_rate: float
    required_investment_usd: float
    time_to_achieve_months: int
    actions: list[str] = field(default_factory=list)

    @property
    def roi(self) -> float:
        annual = self.monthly_revenue_usd * 12
        if self.required_investment_usd <= 0:
            return 0.0
        return round((annual - self.required_investment_usd) / self.required_investment_usd, 3)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "monthly_revenue_usd": round(self.monthly_revenue_usd, 2),
            "growth_rate": self.growth_rate,
            "required_investment_usd": round(self.required_investment_usd, 2),
            "time_to_achieve_months": self.time_to_achieve_months,
            "actions": self.actions,
            "roi": self.roi,
        }


class RevenueOptimizer:
    def __init__(self) -> None:
        self._data: dict = {}
        self._loaded = False

    async def _load(self) -> dict:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_OPTIMIZER_KEY)
                if data and isinstance(data, dict):
                    self._data = data
            except Exception:
                pass
            self._loaded = True
        return self._data

    async def _save(self, data: dict) -> None:
        self._data = data
        try:
            cache = get_cache()
            await cache.set(_OPTIMIZER_KEY, data, ttl_seconds=_OPTIMIZER_TTL)
        except Exception:
            pass

    def identify_quick_wins(
        self,
        current_revenue_usd: float,
        avg_order_value: float,
        conversion_rate: float,
        monthly_visitors: int,
    ) -> list[OptimizationAction]:
        import uuid as _uuid
        actions: list[OptimizationAction] = []

        # Price increase opportunity (if conversion rate is healthy)
        if conversion_rate > 0.02:
            lift = current_revenue_usd * 0.05
            actions.append(OptimizationAction(
                action_id=str(_uuid.uuid4()),
                action_type=ActionType.PRICE_INCREASE,
                title="5% Price Increase",
                description="Conversion rate supports a modest price increase without volume loss",
                estimated_revenue_lift_usd=lift,
                effort_days=1,
                confidence=0.75,
                priority=1,
            ))

        # Bundle offer
        if avg_order_value < 100:
            lift = current_revenue_usd * 0.08
            actions.append(OptimizationAction(
                action_id=str(_uuid.uuid4()),
                action_type=ActionType.BUNDLE_OFFER,
                title="Product Bundle Offer",
                description="Bundle complementary products to increase average order value",
                estimated_revenue_lift_usd=lift,
                effort_days=3,
                confidence=0.70,
                priority=2,
            ))

        # Conversion lift
        if monthly_visitors > 0 and conversion_rate < 0.03:
            potential_conversions = monthly_visitors * 0.01
            lift = potential_conversions * avg_order_value
            actions.append(OptimizationAction(
                action_id=str(_uuid.uuid4()),
                action_type=ActionType.CONVERSION_LIFT,
                title="1% Conversion Rate Lift",
                description="A/B test checkout flow and CTA to improve conversion rate",
                estimated_revenue_lift_usd=lift,
                effort_days=7,
                confidence=0.60,
                priority=3,
            ))

        actions.sort(key=lambda a: a.estimated_revenue_lift_usd, reverse=True)
        return actions

    def build_scenarios(
        self,
        current_monthly_revenue: float,
        current_customers: int,
    ) -> list[RevenueScenario]:
        return [
            RevenueScenario(
                name="conservative",
                monthly_revenue_usd=current_monthly_revenue * 1.15,
                growth_rate=0.15,
                required_investment_usd=current_monthly_revenue * 0.1,
                time_to_achieve_months=3,
                actions=["SEO optimization", "Email nurture sequence", "Price testing"],
            ),
            RevenueScenario(
                name="moderate",
                monthly_revenue_usd=current_monthly_revenue * 1.50,
                growth_rate=0.50,
                required_investment_usd=current_monthly_revenue * 0.25,
                time_to_achieve_months=6,
                actions=["Paid acquisition", "Content marketing", "Affiliate program"],
            ),
            RevenueScenario(
                name="aggressive",
                monthly_revenue_usd=current_monthly_revenue * 3.0,
                growth_rate=2.0,
                required_investment_usd=current_monthly_revenue * 0.80,
                time_to_achieve_months=12,
                actions=["Influencer partnerships", "PR campaign", "New channel expansion", "Product launch"],
            ),
        ]

    async def autonomous_recommendation(
        self,
        current_revenue_usd: float,
        avg_order_value: float = 50.0,
        conversion_rate: float = 0.02,
        monthly_visitors: int = 1000,
    ) -> dict:
        quick_wins = self.identify_quick_wins(
            current_revenue_usd, avg_order_value, conversion_rate, monthly_visitors
        )
        scenarios = self.build_scenarios(current_revenue_usd, monthly_visitors)
        total_quick_win_lift = sum(a.estimated_revenue_lift_usd for a in quick_wins)

        recommendation = {
            "quick_wins": [a.to_dict() for a in quick_wins],
            "scenarios": [s.to_dict() for s in scenarios],
            "total_quick_win_lift_usd": round(total_quick_win_lift, 2),
            "recommended_scenario": "moderate" if current_revenue_usd > 1000 else "conservative",
            "generated_at": time.time(),
        }

        data = await self._load()
        data["last_recommendation"] = recommendation
        await self._save(data)
        return recommendation

    def summary(self) -> dict:
        last = self._data.get("last_recommendation", {})
        return {
            "last_recommendation_at": last.get("generated_at", 0),
            "quick_wins_count": len(last.get("quick_wins", [])),
            "total_potential_lift_usd": last.get("total_quick_win_lift_usd", 0.0),
        }


_optimizer_instance: Optional[RevenueOptimizer] = None


def get_revenue_optimizer() -> RevenueOptimizer:
    global _optimizer_instance
    if _optimizer_instance is None:
        _optimizer_instance = RevenueOptimizer()
    return _optimizer_instance
