"""
CFO Agent — Financial modeling, budget allocation, and ROI analysis.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_KEY = "executive:cfo:v1"
_TTL = 90 * 24 * 3600  # 90 days


@dataclass
class FinancialScenario:
    scenario_id: str
    name: str
    revenue_projection: float
    cost_projection: float
    profit_margin: float
    roi: float
    risk_level: str  # "low" | "medium" | "high"
    assumptions: list

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "revenue_projection": self.revenue_projection,
            "cost_projection": self.cost_projection,
            "profit_margin": self.profit_margin,
            "roi": self.roi,
            "risk_level": self.risk_level,
            "assumptions": self.assumptions,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FinancialScenario:
        return cls(
            scenario_id=data["scenario_id"],
            name=data["name"],
            revenue_projection=data.get("revenue_projection", 0.0),
            cost_projection=data.get("cost_projection", 0.0),
            profit_margin=data.get("profit_margin", 0.0),
            roi=data.get("roi", 0.0),
            risk_level=data.get("risk_level", "medium"),
            assumptions=data.get("assumptions", []),
        )


@dataclass
class BudgetAllocation:
    dept: str
    allocated_usd: float
    spent_usd: float
    remaining_usd: float
    efficiency_ratio: float

    def to_dict(self) -> dict:
        return {
            "dept": self.dept,
            "allocated_usd": self.allocated_usd,
            "spent_usd": self.spent_usd,
            "remaining_usd": self.remaining_usd,
            "efficiency_ratio": self.efficiency_ratio,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BudgetAllocation:
        return cls(
            dept=data["dept"],
            allocated_usd=data.get("allocated_usd", 0.0),
            spent_usd=data.get("spent_usd", 0.0),
            remaining_usd=data.get("remaining_usd", 0.0),
            efficiency_ratio=data.get("efficiency_ratio", 1.0),
        )


class CFOAgent:
    def __init__(self) -> None:
        self._scenarios: list[dict] = []
        self._budgets: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._scenarios = data.get("scenarios", [])
                    self._budgets = data.get("budgets", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            payload = {
                "scenarios": self._scenarios[-200:],
                "budgets": self._budgets[-200:],
            }
            await cache.set(_KEY, payload, ttl_seconds=_TTL)
        except Exception:
            pass

    async def model_scenario(
        self,
        name: str,
        revenue_drivers: dict,
        cost_drivers: dict,
    ) -> FinancialScenario:
        await self._load()

        # Compute base financials
        total_revenue = sum(
            float(v) for v in revenue_drivers.values() if isinstance(v, (int, float))
        )
        total_cost = sum(float(v) for v in cost_drivers.values() if isinstance(v, (int, float)))

        if total_revenue == 0:
            total_revenue = 10000.0
        if total_cost == 0:
            total_cost = total_revenue * 0.6

        profit = total_revenue - total_cost
        profit_margin = round(profit / max(total_revenue, 1) * 100, 2)
        roi = round(profit / max(total_cost, 1) * 100, 2)

        risk_level = "low" if roi > 50 else "medium" if roi > 20 else "high"

        ai = get_ai_client()
        rev_text = "; ".join(f"{k}: {v}" for k, v in revenue_drivers.items())
        cost_text = "; ".join(f"{k}: {v}" for k, v in cost_drivers.items())
        resp = await ai.complete(
            system=(
                "You are the CFO. List 3-5 key assumptions for this financial scenario. "
                "Reply with a comma-separated list of assumptions."
            ),
            user=f"Scenario: {name}\nRevenue drivers: {rev_text}\nCost drivers: {cost_text}",
            model=AIModel.FAST,
            max_tokens=150,
        )
        assumptions_text = (
            resp.content if resp.success else "Market conditions stable, customer growth on track"
        )
        assumptions = [a.strip() for a in assumptions_text.split(",") if a.strip()][:5]

        scenario = FinancialScenario(
            scenario_id=str(uuid.uuid4()),
            name=name,
            revenue_projection=round(total_revenue, 2),
            cost_projection=round(total_cost, 2),
            profit_margin=profit_margin,
            roi=roi,
            risk_level=risk_level,
            assumptions=assumptions,
        )
        self._scenarios.append(scenario.to_dict())
        await self._save()
        return scenario

    async def allocate_budget(
        self,
        total_usd: float,
        departments: list[str],
        performance_data: dict,
    ) -> list[BudgetAllocation]:
        await self._load()
        if not departments:
            return []

        # Compute performance-based weights
        weights: dict[str, float] = {}
        for dept in departments:
            perf = performance_data.get(dept, {})
            if isinstance(perf, dict):
                score = perf.get("score", perf.get("roi", perf.get("efficiency", 5.0)))
            elif isinstance(perf, (int, float)):
                score = float(perf)
            else:
                score = 5.0
            weights[dept] = max(float(score), 0.1)

        total_weight = sum(weights.values())
        allocations: list[BudgetAllocation] = []

        for dept in departments:
            share = weights[dept] / total_weight
            allocated = round(total_usd * share, 2)
            spent = round(allocated * 0.7, 2)  # assume 70% spent by default
            remaining = round(allocated - spent, 2)
            efficiency = round(weights[dept] / max(total_weight / len(departments), 0.01), 2)
            ba = BudgetAllocation(
                dept=dept,
                allocated_usd=allocated,
                spent_usd=spent,
                remaining_usd=remaining,
                efficiency_ratio=efficiency,
            )
            allocations.append(ba)
            self._budgets.append(ba.to_dict())

        await self._save()
        return allocations

    async def roi_analysis(
        self,
        investment_usd: float,
        expected_returns: dict,
    ) -> dict:
        total_return = sum(
            float(v) for v in expected_returns.values() if isinstance(v, (int, float))
        )
        if total_return == 0:
            total_return = investment_usd * 1.5

        roi_pct = round((total_return - investment_usd) / max(investment_usd, 1) * 100, 2)
        payback_days = round(investment_usd / max(total_return / 365, 0.01))

        # Simple NPV with 10% discount rate over 1 year
        discount_rate = 0.10
        npv = round(total_return / (1 + discount_rate) - investment_usd, 2)

        recommendation = (
            "Strong buy"
            if roi_pct > 100
            else "Buy" if roi_pct > 30 else "Hold" if roi_pct > 0 else "Avoid"
        )

        return {
            "roi_pct": roi_pct,
            "payback_days": int(payback_days),
            "npv": npv,
            "recommendation": recommendation,
        }

    def burn_rate_warning(self, monthly_burn: float, cash_on_hand: float) -> dict:
        if monthly_burn <= 0:
            return {
                "runway_months": float("inf"),
                "warning": "none",
                "message": "No burn rate — revenue positive",
            }
        runway_months = round(cash_on_hand / monthly_burn, 1)
        if runway_months < 3:
            warning = "critical"
            message = f"Only {runway_months} months of runway — immediate action required"
        elif runway_months < 6:
            warning = "at_risk"
            message = f"{runway_months} months of runway — fundraise or cut costs"
        else:
            warning = "healthy"
            message = f"{runway_months} months of runway — stable"
        return {
            "runway_months": runway_months,
            "warning": warning,
            "message": message,
        }

    def profitability_report(self) -> dict:
        scenarios = [FinancialScenario.from_dict(s) for s in self._scenarios]
        if not scenarios:
            return {
                "total_scenarios": 0,
                "best_scenario": None,
                "avg_roi": 0.0,
                "budget_efficiency": 0.0,
            }
        best = max(scenarios, key=lambda s: s.roi)
        avg_roi = round(sum(s.roi for s in scenarios) / len(scenarios), 2)
        budgets = [BudgetAllocation.from_dict(b) for b in self._budgets]
        avg_efficiency = (
            round(sum(b.efficiency_ratio for b in budgets) / len(budgets), 2) if budgets else 0.0
        )
        return {
            "total_scenarios": len(scenarios),
            "best_scenario": best.name,
            "avg_roi": avg_roi,
            "budget_efficiency": avg_efficiency,
        }


_instance: CFOAgent | None = None


def get_cfo_agent() -> CFOAgent:
    global _instance
    if _instance is None:
        _instance = CFOAgent()
    return _instance
