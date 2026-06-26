from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChurnAnalysis:
    churn_rate_monthly: float
    avg_lifespan_months: float
    cohort_survival: list[float]

    @property
    def ltv_multiplier(self) -> float:
        return 1.0 / max(self.churn_rate_monthly, 0.001)

    def to_dict(self) -> dict:
        return {
            "churn_rate_monthly": self.churn_rate_monthly,
            "avg_lifespan_months": self.avg_lifespan_months,
            "cohort_survival": self.cohort_survival,
            "ltv_multiplier": self.ltv_multiplier,
        }


@dataclass
class CACBreakdown:
    channel: str
    ad_spend: float
    salesperson_cost: float
    tool_cost: float
    total_cac: float
    organic_cac: float
    blended_cac: float

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "ad_spend": self.ad_spend,
            "salesperson_cost": self.salesperson_cost,
            "tool_cost": self.tool_cost,
            "total_cac": self.total_cac,
            "organic_cac": self.organic_cac,
            "blended_cac": self.blended_cac,
        }


class CACLTVAnalyzer:
    def compute_cac(
        self,
        ad_spend: float,
        salesperson_cost: float,
        tool_cost: float,
        new_customers: int,
        channel: str = "blended",
    ) -> CACBreakdown:
        customers = max(new_customers, 1)
        total = (ad_spend + salesperson_cost + tool_cost) / customers
        organic = tool_cost / customers
        blended = (total + organic) / 2
        return CACBreakdown(
            channel=channel,
            ad_spend=ad_spend,
            salesperson_cost=salesperson_cost,
            tool_cost=tool_cost,
            total_cac=round(total, 2),
            organic_cac=round(organic, 2),
            blended_cac=round(blended, 2),
        )

    def compute_ltv(
        self,
        avg_purchase_value: float,
        purchase_frequency_yearly: float,
        gross_margin_pct: float,
        avg_customer_lifespan_years: float,
    ) -> float:
        return round(
            avg_purchase_value
            * purchase_frequency_yearly
            * gross_margin_pct
            * avg_customer_lifespan_years,
            2,
        )

    def compute_churn(self, lost_customers: int, start_customers: int) -> ChurnAnalysis:
        start = max(start_customers, 1)
        rate = lost_customers / start
        rate = min(max(rate, 0.001), 1.0)
        lifespan = 1.0 / rate
        cohort = [round((1 - rate) ** m, 4) for m in range(13)]
        return ChurnAnalysis(
            churn_rate_monthly=round(rate, 4),
            avg_lifespan_months=round(lifespan, 2),
            cohort_survival=cohort,
        )

    def payback_period(
        self,
        cac: float,
        monthly_revenue_per_customer: float,
        margin_pct: float,
    ) -> float:
        monthly_margin = monthly_revenue_per_customer * margin_pct
        if monthly_margin <= 0:
            return float("inf")
        return round(cac / monthly_margin, 2)

    def segment_customers_by_ltv(self, customers: list[dict]) -> dict:
        if not customers:
            return {
                "champions": {"count": 0, "total_ltv": 0.0},
                "loyal": {"count": 0, "total_ltv": 0.0},
                "at_risk": {"count": 0, "total_ltv": 0.0},
                "churned": {"count": 0, "total_ltv": 0.0},
            }

        sorted_by_ltv = sorted(
            customers, key=lambda c: c.get("ltv", c.get("total_spent_usd", 0)), reverse=True
        )
        n = len(sorted_by_ltv)
        champion_cut = max(1, int(n * 0.20))
        loyal_cut = champion_cut + max(1, int(n * 0.30))
        at_risk_cut = loyal_cut + max(1, int(n * 0.30))

        def _segment_stats(segment: list[dict]) -> dict:
            total = sum(c.get("ltv", c.get("total_spent_usd", 0)) for c in segment)
            return {"count": len(segment), "total_ltv": round(total, 2)}

        champions = sorted_by_ltv[:champion_cut]
        loyal = sorted_by_ltv[champion_cut:loyal_cut]
        at_risk = sorted_by_ltv[loyal_cut:at_risk_cut]
        churned = sorted_by_ltv[at_risk_cut:]

        return {
            "champions": _segment_stats(champions),
            "loyal": _segment_stats(loyal),
            "at_risk": _segment_stats(at_risk),
            "churned": _segment_stats(churned),
        }


_analyzer_instance: CACLTVAnalyzer | None = None


def get_cac_ltv_analyzer() -> CACLTVAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = CACLTVAnalyzer()
    return _analyzer_instance
