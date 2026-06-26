"""
Pricing experiments and optimization — runs A/B price tests with
charm, anchor, premium, and competitive strategies.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache

logger = logging.getLogger(__name__)

_REDIS_KEY = "shopify:pricing:v1"
_REDIS_TTL = 86400 * 90  # 90 days

_VALID_STRATEGIES = {"anchor", "charm", "premium", "competitive"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PricingExperiment:
    exp_id: str
    product_id: str
    product_title: str
    control_price: float
    test_price: float
    strategy: str  # "anchor" | "charm" | "premium" | "competitive"
    hypothesis: str
    start_ts: float
    end_ts: float
    status: str = "running"  # "running" | "concluded"
    control_conversions: int = 0
    test_conversions: int = 0
    winner: str = ""
    uplift_pct: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "exp_id": self.exp_id,
            "product_id": self.product_id,
            "product_title": self.product_title,
            "control_price": self.control_price,
            "test_price": self.test_price,
            "strategy": self.strategy,
            "hypothesis": self.hypothesis,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "status": self.status,
            "control_conversions": self.control_conversions,
            "test_conversions": self.test_conversions,
            "winner": self.winner,
            "uplift_pct": self.uplift_pct,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PricingExperiment:
        return cls(**d)

    def is_winner(self) -> bool:
        """Test is a winner if it exceeds control by more than 10%."""
        return self.test_conversions > self.control_conversions * 1.1


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------


class PricingOptimizer:
    """Runs pricing experiments and derives optimal price points."""

    def __init__(self) -> None:
        self._experiments: list[dict] = []
        self._loaded = False

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_REDIS_KEY)
            if data and isinstance(data, list):
                self._experiments = data
        except Exception:
            logger.exception("PricingOptimizer._load failed")
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_REDIS_KEY, self._experiments, ttl_seconds=_REDIS_TTL)
        except Exception:
            logger.exception("PricingOptimizer._save failed")

    # ------------------------------------------------------------------
    # Price strategy helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _charm_price(price: float) -> float:
        """Round to nearest dollar then subtract 0.01 for .99 ending."""
        rounded = round(price)
        return max(0.99, float(rounded) - 0.01)

    @staticmethod
    def _premium_price(price: float) -> float:
        """Round to nearest $5 for premium feel."""
        return round(max(1.0, round(price / 5) * 5), 2)

    @staticmethod
    def _competitive_price(price: float) -> float:
        return round(price * 0.95, 2)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    async def suggest_price(
        self,
        product_id: str,
        title: str,
        current_price: float,
        category: str = "",
    ) -> dict:
        """
        AI-powered pricing suggestion.
        Falls back to heuristic charm pricing if AI is unavailable.
        """
        # Default heuristic
        charm = self._charm_price(current_price)
        strategy = "charm"
        rationale = f"Charm pricing (${charm}) removes a full dollar from perceived cost vs ${current_price}."
        expected_cvr_change = 0.05

        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client  # type: ignore

            ai = get_ai_client()
            if ai is not None:
                system = (
                    "You are a pricing strategist. "
                    "Analyse the product and suggest an optimal price. "
                    "Respond in this exact format:\n"
                    "PRICE: <number>\nSTRATEGY: <charm|anchor|premium|competitive>\n"
                    "RATIONALE: <one sentence>\nEXPECTED_CVR_CHANGE: <decimal like 0.05>"
                )
                user = (
                    f"Product: '{title}' (ID: {product_id}). "
                    f"Current price: ${current_price}. Category: {category or 'general'}. "
                    "Suggest the best price and strategy."
                )
                resp = await ai.complete(system, user, AIModel.STRATEGY, 150)
                if resp and resp.success and resp.content:
                    lines = resp.content.strip().splitlines()
                    parsed: dict[str, str] = {}
                    for line in lines:
                        if ":" in line:
                            k, v = line.split(":", 1)
                            parsed[k.strip().upper()] = v.strip()
                    if "PRICE" in parsed:
                        try:
                            ai_price = float(parsed["PRICE"].replace("$", "").replace(",", ""))
                            strategy = parsed.get("STRATEGY", "charm").lower()
                            if strategy not in _VALID_STRATEGIES:
                                strategy = "charm"
                            rationale = parsed.get("RATIONALE", rationale)
                            try:
                                expected_cvr_change = float(
                                    parsed.get("EXPECTED_CVR_CHANGE", "0.05")
                                )
                            except ValueError:
                                expected_cvr_change = 0.05
                            return {
                                "current_price": current_price,
                                "suggested_price": ai_price,
                                "strategy": strategy,
                                "rationale": rationale,
                                "expected_cvr_change": expected_cvr_change,
                            }
                        except ValueError:
                            pass
        except Exception:
            logger.debug("AI price suggestion failed, using heuristic")

        return {
            "current_price": current_price,
            "suggested_price": charm,
            "strategy": strategy,
            "rationale": rationale,
            "expected_cvr_change": expected_cvr_change,
        }

    async def create_experiment(
        self,
        product_id: str,
        title: str,
        control_price: float,
        strategy: str = "charm",
    ) -> PricingExperiment:
        """Create a pricing experiment with test price derived from strategy."""
        await self._load()

        if strategy not in _VALID_STRATEGIES:
            strategy = "charm"

        # Derive test price
        if strategy == "charm":
            test_price = self._charm_price(control_price)
        elif strategy == "anchor":
            # Anchor: control price remains but we suggest showing a higher MSRP
            test_price = control_price  # price stays, display changes
        elif strategy == "competitive":
            test_price = self._competitive_price(control_price)
        else:  # premium
            test_price = self._premium_price(control_price)

        hypotheses = {
            "charm": f"Changing price from ${control_price} to ${test_price} (.99 ending) will increase CVR by 5%.",
            "anchor": f"Displaying a higher MSRP anchor next to ${control_price} will increase perceived value.",
            "competitive": f"Reducing price to ${test_price} (5% below ${control_price}) will capture more market share.",
            "premium": f"Rounding price to ${test_price} signals premium quality and may increase AOV.",
        }

        now = time.time()
        exp = PricingExperiment(
            exp_id=str(uuid.uuid4()),
            product_id=product_id,
            product_title=title,
            control_price=control_price,
            test_price=test_price,
            strategy=strategy,
            hypothesis=hypotheses[strategy],
            start_ts=now,
            end_ts=now + 14 * 24 * 3600,  # 14-day default
            status="running",
            created_at=now,
        )
        self._experiments.append(exp.to_dict())
        await self._save()
        return exp

    async def conclude_experiment(
        self, exp_id: str, control_conv: int, test_conv: int
    ) -> PricingExperiment:
        """Record final conversion counts and determine winner."""
        await self._load()
        for e in self._experiments:
            if e["exp_id"] == exp_id:
                e["status"] = "concluded"
                e["control_conversions"] = control_conv
                e["test_conversions"] = test_conv
                e["end_ts"] = time.time()
                if test_conv > control_conv * 1.1:
                    e["winner"] = "test"
                    e["uplift_pct"] = round(
                        ((test_conv - control_conv) / max(control_conv, 1)) * 100, 2
                    )
                elif control_conv > test_conv * 1.1:
                    e["winner"] = "control"
                    e["uplift_pct"] = 0.0
                else:
                    e["winner"] = "inconclusive"
                    e["uplift_pct"] = 0.0
                await self._save()
                return PricingExperiment.from_dict(e)
        raise ValueError(f"Experiment {exp_id} not found")

    def optimal_price_points(self, price: float) -> list[float]:
        """Return 5 price points to A/B test around a given price."""
        charm = self._charm_price(price)
        premium = self._premium_price(price)
        competitive = self._competitive_price(price)
        p97 = round(price * 0.97, 2)
        half_off = round(price * 0.50, 2)
        # Deduplicate while preserving order
        seen: set[float] = set()
        result: list[float] = []
        for pt in [charm, premium, competitive, p97, half_off]:
            if pt not in seen:
                seen.add(pt)
                result.append(pt)
        # Pad to 5 if dedup removed some
        extras = [round(price * f, 2) for f in [0.9, 0.85, 0.80, 0.75, 0.70]]
        for e in extras:
            if len(result) >= 5:
                break
            if e not in seen:
                seen.add(e)
                result.append(e)
        return result[:5]

    def pricing_insights(self) -> dict:
        running = [e for e in self._experiments if e.get("status") == "running"]
        concluded = [e for e in self._experiments if e.get("status") == "concluded"]
        winners = [e for e in concluded if e.get("winner") == "test"]
        win_rate = len(winners) / max(len(concluded), 1)
        avg_uplift = sum(e.get("uplift_pct", 0.0) for e in winners) / max(len(winners), 1)
        return {
            "running_experiments": len(running),
            "concluded_experiments": len(concluded),
            "win_rate": round(win_rate, 3),
            "avg_uplift": round(avg_uplift, 2),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_optimizer: PricingOptimizer | None = None


def get_pricing_optimizer() -> PricingOptimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = PricingOptimizer()
    return _optimizer
