"""
Dynamic pricing intelligence for Shopify products.

Provides deterministic price recommendations, demand elasticity estimation,
and margin analysis without external API calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums and data models
# ---------------------------------------------------------------------------


class PricingStrategy(str, Enum):
    PENETRATION = "penetration"       # Low price to gain market share
    SKIMMING = "skimming"             # High price for early adopters
    COMPETITIVE = "competitive"       # Match the market
    VALUE_BASED = "value_based"       # Price on perceived value
    DYNAMIC = "dynamic"               # Adjust based on demand signals


@dataclass
class PricePoint:
    product_id: str
    current_price: float
    min_price: float
    max_price: float
    recommended_price: float
    strategy: PricingStrategy
    confidence: float
    reasoning: str


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------


class PricingOptimizer:
    """
    Provides pricing recommendations using deterministic heuristics.

    All core calculations are synchronous — no external calls required.
    """

    def recommend_price(
        self,
        product_id: str,
        current_price: float,
        cost_basis: float,
        category: str,
        competition_avg: float | None = None,
    ) -> PricePoint:
        """
        Return a PricePoint with a recommended price and strategy.

        Rules:
        - If cost_basis > 0:  min = cost_basis × 1.2, max = cost_basis × 4.0
        - If competition_avg: recommended = competition_avg × 0.95 (competitive)
        - Else:               recommended = cost_basis × 2.5  (value-based)
        - Confidence = 0.9 if competition data is available, else 0.6
        """
        if cost_basis > 0:
            min_price = cost_basis * 1.2
            max_price = cost_basis * 4.0
        else:
            # No cost data — use current price as floor anchor
            min_price = current_price * 0.7
            max_price = current_price * 2.0

        if competition_avg is not None:
            recommended = competition_avg * 0.95
            strategy = PricingStrategy.COMPETITIVE
            confidence = 0.9
            reasoning = (
                f"Priced 5% below market average (${competition_avg:.2f}) "
                f"to remain competitive in the {category} category."
            )
        else:
            if cost_basis > 0:
                recommended = cost_basis * 2.5
            else:
                recommended = current_price
            strategy = PricingStrategy.VALUE_BASED
            confidence = 0.6
            reasoning = (
                f"Value-based pricing at 2.5× cost basis "
                f"for the {category} category. "
                "Consider gathering competitor pricing to improve confidence."
            )

        # Clamp recommended to [min_price, max_price]
        recommended = max(min_price, min(recommended, max_price))

        return PricePoint(
            product_id=product_id,
            current_price=current_price,
            min_price=round(min_price, 2),
            max_price=round(max_price, 2),
            recommended_price=round(recommended, 2),
            strategy=strategy,
            confidence=confidence,
            reasoning=reasoning,
        )

    async def batch_optimize(
        self, products: list[dict]
    ) -> list[PricePoint]:
        """
        Run recommend_price for each product dict and return all PricePoints.

        Expected keys per product dict:
          product_id, current_price, cost_basis, category, competition_avg (optional)
        """
        results: list[PricePoint] = []
        for p in products:
            try:
                pp = self.recommend_price(
                    product_id=str(p.get("product_id", "")),
                    current_price=float(p.get("current_price", 0.0)),
                    cost_basis=float(p.get("cost_basis", 0.0)),
                    category=str(p.get("category", "general")),
                    competition_avg=p.get("competition_avg"),
                )
                results.append(pp)
            except Exception:
                logger.exception(
                    "PricingOptimizer.batch_optimize: error processing product %s",
                    p.get("product_id"),
                )
        return results

    def demand_elasticity_estimate(
        self, price_changes: list[tuple[float, int]]
    ) -> float:
        """
        Estimate price elasticity of demand via simple linear regression.

        Each tuple is (price_change_pct, volume_change_pct).
        Returns the elasticity coefficient (slope of volume ~ price).
        Returns 0.0 if fewer than 2 data points or degenerate input.
        """
        if len(price_changes) < 2:
            return 0.0

        xs = [p for p, _ in price_changes]
        ys = [v for _, v in price_changes]
        n = len(xs)

        sum_x = sum(xs)
        sum_y = sum(ys)
        sum_xy = sum(x * y for x, y in zip(xs, ys))
        sum_x2 = sum(x * x for x in xs)

        denominator = n * sum_x2 - sum_x ** 2
        if denominator == 0:
            return 0.0

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        return round(slope, 4)

    def margin_analysis(
        self,
        revenue: float,
        cogs: float,
        operating_costs: float,
    ) -> dict[str, Any]:
        """
        Calculate gross and net margin metrics.

        Returns:
            gross_margin_pct: (revenue - cogs) / revenue × 100
            net_margin_pct:   (revenue - cogs - operating_costs) / revenue × 100
            contribution_margin: revenue - cogs
        """
        if revenue <= 0:
            return {
                "gross_margin_pct": 0.0,
                "net_margin_pct": 0.0,
                "contribution_margin": 0.0,
            }

        gross_profit = revenue - cogs
        net_profit = gross_profit - operating_costs

        return {
            "gross_margin_pct": round((gross_profit / revenue) * 100, 2),
            "net_margin_pct": round((net_profit / revenue) * 100, 2),
            "contribution_margin": round(gross_profit, 2),
        }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_optimizer_instance: PricingOptimizer | None = None


def get_pricing_optimizer() -> PricingOptimizer:
    """Return the shared PricingOptimizer singleton."""
    global _optimizer_instance
    if _optimizer_instance is None:
        _optimizer_instance = PricingOptimizer()
    return _optimizer_instance
