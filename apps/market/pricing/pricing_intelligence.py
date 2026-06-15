"""
PricingIntelligence — Market pricing analysis, competitor benchmarking,
and dynamic price recommendations for ARIA AI.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_KEY = "market:pricing:v1"
_TTL = 86400 * 14  # 14 days


@dataclass
class PricePoint:
    price_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    product_name: str = ""
    category: str = ""
    our_price: float = 0.0
    competitor_prices: list = field(default_factory=list)   # list of {"competitor": str, "price": float}
    market_avg: float = 0.0
    market_min: float = 0.0
    market_max: float = 0.0
    positioning: str = ""    # "premium", "competitive", "budget", "value"
    recommended_price: float = 0.0
    price_elasticity: str = "medium"   # "low"|"medium"|"high"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "price_id": self.price_id,
            "product_name": self.product_name,
            "category": self.category,
            "our_price": self.our_price,
            "competitor_prices": self.competitor_prices,
            "market_avg": self.market_avg,
            "market_min": self.market_min,
            "market_max": self.market_max,
            "positioning": self.positioning,
            "recommended_price": self.recommended_price,
            "price_elasticity": self.price_elasticity,
            "created_at": self.created_at,
        }


@dataclass
class PricingStrategy:
    strategy_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    strategy_type: str = ""   # "penetration", "skimming", "competitive", "value_based", "dynamic"
    niche: str = ""
    rationale: str = ""
    initial_price: float = 0.0
    target_price: float = 0.0
    price_increases: list = field(default_factory=list)    # [{"at_customers": 100, "new_price": 79}]
    discount_thresholds: list = field(default_factory=list)  # [{"min_qty": 5, "discount_pct": 10}]
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_type": self.strategy_type,
            "niche": self.niche,
            "rationale": self.rationale,
            "initial_price": self.initial_price,
            "target_price": self.target_price,
            "price_increases": self.price_increases,
            "discount_thresholds": self.discount_thresholds,
            "created_at": self.created_at,
        }


class PricingIntelligence:
    def __init__(self) -> None:
        self._price_points: list[dict] = []
        self._strategies: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._price_points = data.get("price_points", [])
                    self._strategies = data.get("strategies", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _KEY,
                {"price_points": self._price_points[-200:], "strategies": self._strategies[-100:]},
                ttl_seconds=_TTL,
            )
        except Exception:
            pass

    async def analyze_pricing(
        self,
        product_name: str,
        category: str,
        our_price: float,
        competitor_data: list = [],
    ) -> PricePoint:
        await self._load()
        pp = PricePoint(product_name=product_name, category=category, our_price=our_price)
        pp.competitor_prices = list(competitor_data)

        if competitor_data:
            prices = [c.get("price", 0.0) for c in competitor_data if c.get("price", 0.0) > 0]
            if prices:
                pp.market_avg = sum(prices) / len(prices)
                pp.market_min = min(prices)
                pp.market_max = max(prices)

        # AI estimates competitor pricing if no data provided
        if not competitor_data or pp.market_avg == 0.0:
            ai = get_ai_client()
            try:
                resp = await ai.complete(
                    system="You are a pricing analyst. Estimate competitor pricing based on product and category.",
                    user=f"Product: {product_name}, Category: {category}, Our price: ${our_price}. Estimate market average price. Reply with just a number like: Market average: $85",
                    model=AIModel.FAST,
                    max_tokens=100,
                )
                if resp.success:
                    import re
                    nums = re.findall(r'\$?([\d.]+)', resp.content)
                    if nums:
                        pp.market_avg = float(nums[0])
                        pp.market_min = pp.market_avg * 0.7
                        pp.market_max = pp.market_avg * 1.4
            except Exception:
                pp.market_avg = our_price
                pp.market_min = our_price * 0.8
                pp.market_max = our_price * 1.3

        # Positioning logic
        if pp.market_avg > 0:
            if our_price > pp.market_avg * 1.2:
                pp.positioning = "premium"
            elif our_price < pp.market_avg * 0.8:
                pp.positioning = "budget"
            else:
                pp.positioning = "competitive"
        else:
            pp.positioning = "competitive"

        # AI determines recommended_price
        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system="You are a pricing strategist. Recommend optimal price for market success.",
                user=f"Product: {product_name}, Category: {category}, Our price: ${our_price}, Market avg: ${pp.market_avg:.2f}, Positioning: {pp.positioning}. Recommend a specific price. Reply like: Recommended price: $79",
                model=AIModel.FAST,
                max_tokens=150,
            )
            if resp.success:
                import re
                nums = re.findall(r'\$?([\d.]+)', resp.content)
                if nums:
                    pp.recommended_price = float(nums[0])
        except Exception:
            pp.recommended_price = pp.market_avg if pp.market_avg > 0 else our_price

        if pp.recommended_price == 0.0:
            pp.recommended_price = pp.market_avg if pp.market_avg > 0 else our_price

        self._price_points.append(pp.to_dict())
        await self._save()
        return pp

    async def build_strategy(
        self,
        niche: str,
        product_type: str,
        target_margin_pct: float = 60.0,
    ) -> PricingStrategy:
        await self._load()
        strategy = PricingStrategy(niche=niche)

        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system="You are a pricing strategist. Build a complete pricing strategy with rationale.",
                user=f"Niche: {niche}, Product type: {product_type}, Target margin: {target_margin_pct}%. Provide strategy type (penetration/skimming/competitive/value_based/dynamic), initial price, target price, rationale, and price increase milestones.",
                model=AIModel.STRATEGY,
                max_tokens=400,
            )
            if resp.success:
                content = resp.content
                strategy.rationale = content

                import re
                # Extract strategy type
                for st in ["penetration", "skimming", "competitive", "value_based", "dynamic"]:
                    if st in content.lower():
                        strategy.strategy_type = st
                        break
                if not strategy.strategy_type:
                    strategy.strategy_type = "competitive"

                # Extract prices
                prices = re.findall(r'\$?([\d.]+)', content)
                if len(prices) >= 2:
                    strategy.initial_price = float(prices[0])
                    strategy.target_price = float(prices[1])
                elif len(prices) == 1:
                    strategy.initial_price = float(prices[0])
                    strategy.target_price = strategy.initial_price * 1.3

                strategy.price_increases = [{"at_customers": 100, "new_price": strategy.target_price}]
                strategy.discount_thresholds = [{"min_qty": 5, "discount_pct": 10}]
        except Exception:
            strategy.strategy_type = "competitive"
            strategy.rationale = f"Competitive pricing strategy for {niche}"
            strategy.initial_price = 49.0
            strategy.target_price = 79.0
            strategy.price_increases = [{"at_customers": 100, "new_price": 79.0}]
            strategy.discount_thresholds = [{"min_qty": 5, "discount_pct": 10}]

        if not strategy.strategy_type:
            strategy.strategy_type = "competitive"
        if strategy.initial_price == 0.0:
            strategy.initial_price = 49.0
        if strategy.target_price == 0.0:
            strategy.target_price = strategy.initial_price * 1.3
        if not strategy.price_increases:
            strategy.price_increases = [{"at_customers": 100, "new_price": strategy.target_price}]
        if not strategy.discount_thresholds:
            strategy.discount_thresholds = [{"min_qty": 5, "discount_pct": 10}]

        self._strategies.append(strategy.to_dict())
        await self._save()
        return strategy

    async def detect_price_elasticity(self, product: str, price_range: tuple) -> str:
        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system="You are an economist. Estimate price elasticity for a product.",
                user=f"Product: {product}, Price range tested: ${price_range[0]} to ${price_range[1]}. Is demand elasticity low, medium, or high? Reply with just one word: low, medium, or high.",
                model=AIModel.FAST,
                max_tokens=50,
            )
            if resp.success:
                content = resp.content.lower().strip()
                for el in ["low", "medium", "high"]:
                    if el in content:
                        return el
        except Exception:
            pass
        return "medium"

    async def dynamic_price_suggestion(
        self,
        product: str,
        inventory_level: str = "normal",
        demand_signal: str = "stable",
    ) -> dict:
        await self._load()
        # Find existing price point for product
        base_price = 0.0
        for pp in self._price_points:
            if pp.get("product_name", "").lower() == product.lower():
                base_price = pp.get("our_price", 0.0)
                break
        if base_price == 0.0:
            base_price = 100.0  # default

        adjustment_pct = 0.0
        reasoning = ""

        if demand_signal == "high" and inventory_level == "low":
            adjustment_pct = 10.0  # increase 10%
            reasoning = "High demand + low inventory — increase price"
        elif demand_signal == "high":
            adjustment_pct = 5.0
            reasoning = "High demand — slight price increase"
        elif demand_signal == "low":
            adjustment_pct = -7.5
            reasoning = "Low demand — decrease price to stimulate sales"
        elif inventory_level == "high":
            adjustment_pct = -5.0
            reasoning = "High inventory — discount to clear stock"
        else:
            reasoning = "Stable conditions — maintain current price"

        # AI refines reasoning
        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system="You are a dynamic pricing engine.",
                user=f"Product: {product}, Inventory: {inventory_level}, Demand: {demand_signal}, Base price: ${base_price}. Suggest price adjustment percentage and reasoning.",
                model=AIModel.FAST,
                max_tokens=150,
            )
            if resp.success:
                reasoning = resp.content
                import re
                nums = re.findall(r'([+-]?[\d.]+)%', resp.content)
                if nums:
                    adjustment_pct = float(nums[0])
        except Exception:
            pass

        suggested_price = base_price * (1 + adjustment_pct / 100)
        return {
            "suggested_price": round(suggested_price, 2),
            "adjustment_pct": adjustment_pct,
            "reasoning": reasoning,
        }

    def pricing_dashboard(self) -> dict:
        by_positioning: dict = {}
        total_price = 0.0
        count = 0
        for pp in self._price_points:
            pos = pp.get("positioning", "unknown")
            by_positioning[pos] = by_positioning.get(pos, 0) + 1
            total_price += pp.get("our_price", 0.0)
            count += 1
        return {
            "total_price_points": len(self._price_points),
            "by_positioning": by_positioning,
            "avg_price": round(total_price / count, 2) if count > 0 else 0.0,
            "strategies_built": len(self._strategies),
        }

    def competitive_gaps(self) -> list[dict]:
        """Returns price_points where our_price > recommended_price * 1.1 (overpriced)."""
        return [
            pp for pp in self._price_points
            if pp.get("recommended_price", 0.0) > 0
            and pp.get("our_price", 0.0) > pp.get("recommended_price", 0.0) * 1.1
        ]

    def recent_analyses(self, limit: int = 10) -> list[dict]:
        return sorted(self._price_points, key=lambda x: x.get("created_at", 0), reverse=True)[:limit]


# ── Singleton ────────────────────────────────────────────────────────────────
_instance: Optional[PricingIntelligence] = None


def get_pricing_intelligence() -> PricingIntelligence:
    global _instance
    if _instance is None:
        _instance = PricingIntelligence()
    return _instance
