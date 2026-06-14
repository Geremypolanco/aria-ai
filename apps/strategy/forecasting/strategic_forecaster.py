from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.memory.redis_client import get_cache

_CACHE_KEY = "strategy:forecasts:v1"
_CACHE_TTL = 86400 * 90  # 90 days


class GrowthModel(str, Enum):
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    S_CURVE = "s_curve"
    PLATEAU = "plateau"


@dataclass
class ForecastScenario:
    scenario_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "forecast"
    model: GrowthModel = GrowthModel.EXPONENTIAL
    initial_revenue: float = 0.0
    growth_rate: float = 0.1
    months: int = 12
    projections: list[dict] = field(default_factory=list)
    total_projected_revenue: float = 0.0
    breakeven_month: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "model": self.model.value,
            "initial_revenue": self.initial_revenue,
            "growth_rate": self.growth_rate,
            "months": self.months,
            "projections": self.projections,
            "total_projected_revenue": self.total_projected_revenue,
            "breakeven_month": self.breakeven_month,
            "created_at": self.created_at,
        }


def _compute_projections(
    initial_revenue: float,
    growth_rate: float,
    months: int,
    model: GrowthModel,
) -> tuple[list[dict], float, int]:
    projections: list[dict] = []
    cumulative = 0.0
    breakeven_threshold = initial_revenue * 12
    breakeven_month = 0

    cap = initial_revenue * 20.0
    k = 0.5
    midpoint = months / 2.0

    for m in range(1, months + 1):
        if model == GrowthModel.LINEAR:
            revenue = initial_revenue + initial_revenue * growth_rate * m
        elif model == GrowthModel.EXPONENTIAL:
            revenue = initial_revenue * ((1.0 + growth_rate) ** m)
        elif model == GrowthModel.S_CURVE:
            revenue = cap / (1.0 + math.exp(-k * (m - midpoint)))
        elif model == GrowthModel.PLATEAU:
            if m <= 6:
                revenue = initial_revenue * ((1.0 + growth_rate) ** m)
            else:
                half_rate = growth_rate / 2.0
                base_at_6 = initial_revenue * ((1.0 + growth_rate) ** 6)
                revenue = base_at_6 * ((1.0 + half_rate) ** (m - 6))
        else:
            revenue = initial_revenue * ((1.0 + growth_rate) ** m)

        revenue = max(0.0, revenue)
        # Estimate customers: assume $50 AOV
        customers = int(revenue / 50.0) if revenue > 0 else 0
        cumulative += revenue

        if breakeven_month == 0 and cumulative >= breakeven_threshold:
            breakeven_month = m

        projections.append({
            "month": m,
            "revenue_usd": round(revenue, 2),
            "customers": customers,
            "cumulative_revenue_usd": round(cumulative, 2),
        })

    return projections, round(cumulative, 2), breakeven_month


class StrategicForecaster:
    def __init__(self) -> None:
        self._scenarios: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._scenarios = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._scenarios, ttl_seconds=_CACHE_TTL)
        except Exception:
            pass

    async def forecast(
        self,
        initial_revenue: float,
        growth_rate: float,
        months: int = 12,
        model: GrowthModel = GrowthModel.EXPONENTIAL,
        name: str = "forecast",
    ) -> ForecastScenario:
        await self._load()

        projections, total, breakeven = _compute_projections(
            initial_revenue, growth_rate, months, model
        )

        scenario = ForecastScenario(
            name=name,
            model=model,
            initial_revenue=initial_revenue,
            growth_rate=growth_rate,
            months=months,
            projections=projections,
            total_projected_revenue=total,
            breakeven_month=breakeven,
        )

        self._scenarios.append(scenario.to_dict())
        await self._save()
        return scenario

    async def compare_scenarios(self, scenarios: list[ForecastScenario]) -> dict:
        if not scenarios:
            return {
                "best_12m_revenue": 0.0,
                "best_scenario": "",
                "worst_scenario": "",
                "recommended": "",
            }

        def _get_12m_revenue(s: ForecastScenario) -> float:
            # Get revenue at month 12 (or last month if < 12)
            if not s.projections:
                return 0.0
            target = next(
                (p for p in s.projections if p["month"] == 12),
                s.projections[-1]
            )
            return target["revenue_usd"]

        scored = sorted(scenarios, key=_get_12m_revenue, reverse=True)
        best = scored[0]
        worst = scored[-1]
        best_revenue = _get_12m_revenue(best)

        # Recommended: balance of revenue and breakeven speed
        recommended = min(
            scenarios,
            key=lambda s: (s.breakeven_month if s.breakeven_month > 0 else 9999) - _get_12m_revenue(s) / 1000
        )

        return {
            "best_12m_revenue": best_revenue,
            "best_scenario": best.name,
            "worst_scenario": worst.name,
            "recommended": recommended.name,
        }

    async def stress_test(
        self,
        base_forecast: ForecastScenario,
        shock_month: int,
        shock_pct: float,
    ) -> ForecastScenario:
        modified_projections = []
        cumulative = 0.0
        breakeven_threshold = base_forecast.initial_revenue * 12
        breakeven_month = 0

        for proj in base_forecast.projections:
            m = proj["month"]
            revenue = proj["revenue_usd"]

            if m >= shock_month:
                revenue = revenue * (1.0 - shock_pct)

            revenue = max(0.0, revenue)
            customers = int(revenue / 50.0) if revenue > 0 else 0
            cumulative += revenue

            if breakeven_month == 0 and cumulative >= breakeven_threshold:
                breakeven_month = m

            modified_projections.append({
                "month": m,
                "revenue_usd": round(revenue, 2),
                "customers": customers,
                "cumulative_revenue_usd": round(cumulative, 2),
            })

        return ForecastScenario(
            name=f"{base_forecast.name}_stressed_m{shock_month}_{int(shock_pct*100)}pct",
            model=base_forecast.model,
            initial_revenue=base_forecast.initial_revenue,
            growth_rate=base_forecast.growth_rate,
            months=base_forecast.months,
            projections=modified_projections,
            total_projected_revenue=round(cumulative, 2),
            breakeven_month=breakeven_month,
        )

    def summary(self) -> dict:
        if not self._scenarios:
            return {"total_scenarios": 0, "latest_12m_projection": 0.0}

        latest = self._scenarios[-1]
        projections = latest.get("projections", [])
        month_12 = next(
            (p for p in projections if p["month"] == 12),
            projections[-1] if projections else None
        )
        latest_12m = month_12["revenue_usd"] if month_12 else 0.0

        return {
            "total_scenarios": len(self._scenarios),
            "latest_12m_projection": latest_12m,
        }


_forecaster_instance: Optional[StrategicForecaster] = None


def get_strategic_forecaster() -> StrategicForecaster:
    global _forecaster_instance
    if _forecaster_instance is None:
        _forecaster_instance = StrategicForecaster()
    return _forecaster_instance
