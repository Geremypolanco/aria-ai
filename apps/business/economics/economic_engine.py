from __future__ import annotations

import time
from dataclasses import dataclass

from apps.core.memory.redis_client import get_cache

_ECONOMICS_KEY = "economics:v1"
_ECONOMICS_TTL = 86400 * 90


@dataclass
class UnitEconomics:
    channel: str
    cac_usd: float
    ltv_usd: float
    payback_period_months: float
    ltv_cac_ratio: float
    contribution_margin: float
    break_even_customers: int

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "cac_usd": self.cac_usd,
            "ltv_usd": self.ltv_usd,
            "payback_period_months": self.payback_period_months,
            "ltv_cac_ratio": self.ltv_cac_ratio,
            "contribution_margin": self.contribution_margin,
            "break_even_customers": self.break_even_customers,
        }

    @classmethod
    def from_dict(cls, d: dict) -> UnitEconomics:
        return cls(**d)


@dataclass
class EconomicOpportunity:
    opportunity_id: str
    name: str
    channel: str
    expected_cac: float
    expected_ltv: float
    market_size: int
    required_investment: float
    projected_roi: float
    risk_level: str
    payback_months: float

    @property
    def ltv_cac_ratio(self) -> float:
        return self.expected_ltv / max(self.expected_cac, 0.01)

    def to_dict(self) -> dict:
        return {
            "opportunity_id": self.opportunity_id,
            "name": self.name,
            "channel": self.channel,
            "expected_cac": self.expected_cac,
            "expected_ltv": self.expected_ltv,
            "market_size": self.market_size,
            "required_investment": self.required_investment,
            "projected_roi": self.projected_roi,
            "risk_level": self.risk_level,
            "payback_months": self.payback_months,
        }

    @classmethod
    def from_dict(cls, d: dict) -> EconomicOpportunity:
        return cls(**d)


@dataclass
class RevenueProjection:
    month: int
    customers: int
    revenue_usd: float
    costs_usd: float
    profit_usd: float

    @property
    def margin(self) -> float:
        return self.profit_usd / max(self.revenue_usd, 0.01)

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "customers": self.customers,
            "revenue_usd": self.revenue_usd,
            "costs_usd": self.costs_usd,
            "profit_usd": self.profit_usd,
            "margin": self.margin,
        }


class EconomicEngine:
    def __init__(self) -> None:
        self._data: dict = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _load(self) -> dict:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_ECONOMICS_KEY)
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
            await cache.set(_ECONOMICS_KEY, data, ttl_seconds=_ECONOMICS_TTL)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Core computations (sync — no I/O needed)
    # ------------------------------------------------------------------

    def compute_unit_economics(
        self,
        channel: str,
        total_acquisition_spend: float,
        total_customers: int,
        avg_order_value: float,
        avg_orders_per_year: float,
        avg_lifespan_years: float,
        cogs_pct: float = 0.3,
    ) -> UnitEconomics:
        customers = max(total_customers, 1)
        cac = total_acquisition_spend / customers
        ltv = avg_order_value * avg_orders_per_year * avg_lifespan_years * (1 - cogs_pct)
        monthly_margin = avg_order_value * (1 - cogs_pct) * (avg_orders_per_year / 12)
        payback = cac / max(monthly_margin, 0.01)
        ltv_cac = ltv / max(cac, 0.01)
        contribution_margin = 1 - cogs_pct
        break_even = int(total_acquisition_spend / max(ltv, 0.01)) + 1

        return UnitEconomics(
            channel=channel,
            cac_usd=round(cac, 2),
            ltv_usd=round(ltv, 2),
            payback_period_months=round(payback, 2),
            ltv_cac_ratio=round(ltv_cac, 2),
            contribution_margin=round(contribution_margin, 3),
            break_even_customers=break_even,
        )

    def score_opportunity(self, opp: EconomicOpportunity) -> float:
        # LTV/CAC score: capped at 40 points (ratio*20, max 40)
        ltv_cac_score = min(40.0, opp.ltv_cac_ratio * 20)
        # ROI score: capped at 30 points (roi*10, max 30)
        roi_score = min(30.0, opp.projected_roi * 10)
        # Payback speed: faster is better, capped at 20
        payback_score = min(20.0, max(0.0, 20.0 - opp.payback_months))
        # Risk adjustment
        risk_adj = {"low": 10.0, "medium": 0.0, "high": -10.0}.get(opp.risk_level.lower(), 0.0)

        return round(ltv_cac_score + roi_score + payback_score + risk_adj, 2)

    async def rank_opportunities(
        self, opportunities: list[EconomicOpportunity]
    ) -> list[EconomicOpportunity]:
        scored = sorted(opportunities, key=lambda o: self.score_opportunity(o), reverse=True)
        top_10 = scored[:10]
        try:
            data = await self._load()
            data["top_opportunities"] = [o.to_dict() for o in top_10]
            await self._save(data)
        except Exception:
            pass
        return scored

    def forecast_revenue(
        self,
        initial_customers: int,
        monthly_growth_rate: float,
        avg_ltv: float,
        months: int = 12,
    ) -> list[RevenueProjection]:
        projections: list[RevenueProjection] = []
        customers = initial_customers
        for month in range(months + 1):
            revenue = customers * (avg_ltv / 12)
            costs = revenue * 0.4
            profit = revenue - costs
            projections.append(
                RevenueProjection(
                    month=month,
                    customers=int(customers),
                    revenue_usd=round(revenue, 2),
                    costs_usd=round(costs, 2),
                    profit_usd=round(profit, 2),
                )
            )
            customers *= 1 + monthly_growth_rate
        return projections

    async def economic_report(self) -> dict:
        try:
            data = await self._load()
        except Exception:
            data = {}

        unit_economics_raw = data.get("unit_economics", {})
        unit_economics = (
            {k: UnitEconomics.from_dict(v) for k, v in unit_economics_raw.items()}
            if unit_economics_raw
            else {}
        )
        top_opps = data.get("top_opportunities", [])
        forecast = self.forecast_revenue(100, 0.05, 200)

        return {
            "unit_economics": {k: v.to_dict() for k, v in unit_economics.items()},
            "top_opportunities": top_opps,
            "12_month_forecast": [p.to_dict() for p in forecast],
            "generated_at": time.time(),
        }

    def optimal_budget_allocation(
        self, total_budget: float, channels_data: list[dict]
    ) -> dict[str, float]:
        if not channels_data:
            return {}

        scored: list[tuple[str, float]] = []
        for ch in channels_data:
            opp = EconomicOpportunity(
                opportunity_id="",
                name=ch.get("name", ""),
                channel=ch.get("channel", ""),
                expected_cac=ch.get("expected_cac", 100),
                expected_ltv=ch.get("expected_ltv", 300),
                market_size=ch.get("market_size", 1000),
                required_investment=ch.get("required_investment", 0),
                projected_roi=ch.get("projected_roi", 1.0),
                risk_level=ch.get("risk_level", "medium"),
                payback_months=ch.get("payback_months", 6),
            )
            scored.append((ch.get("channel", "unknown"), self.score_opportunity(opp)))

        total_score = sum(s for _, s in scored)
        if total_score <= 0:
            equal_share = total_budget / len(scored)
            return {ch: round(equal_share, 2) for ch, _ in scored}

        return {ch: round(total_budget * (s / total_score), 2) for ch, s in scored}

    def summary(self) -> dict:
        return {
            "best_channel_by_roi": "unknown",
            "avg_ltv_cac": 0.0,
            "total_projected_12mo_revenue": 0.0,
        }


_engine_instance: EconomicEngine | None = None


def get_economic_engine() -> EconomicEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = EconomicEngine()
    return _engine_instance
