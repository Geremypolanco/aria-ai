"""
Flash sale management system — creates, activates and tracks time-limited sales
with AI-generated urgency copy and smart product selection.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

try:
    from apps.core.memory.redis_client import get_cache  # type: ignore
    from apps.core.tools.ai_client import get_ai_client, AIModel  # type: ignore
except ImportError:
    get_cache = None  # type: ignore
    get_ai_client = None  # type: ignore
    AIModel = None  # type: ignore

logger = logging.getLogger(__name__)

_REDIS_KEY = "shopify:flash_sales:v1"
_REDIS_TTL = 86400 * 60  # 60 days


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class FlashSale:
    sale_id: str
    name: str
    product_ids: list[str]
    discount_pct: float  # 0.0–1.0
    original_prices: dict[str, float]
    sale_prices: dict[str, float]
    start_ts: float
    end_ts: float
    status: str  # "planned" | "active" | "ended" | "cancelled"
    revenue_generated: float = 0.0
    units_sold: int = 0
    created_at: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "sale_id": self.sale_id,
            "name": self.name,
            "product_ids": self.product_ids,
            "discount_pct": self.discount_pct,
            "original_prices": self.original_prices,
            "sale_prices": self.sale_prices,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "status": self.status,
            "revenue_generated": self.revenue_generated,
            "units_sold": self.units_sold,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FlashSale":
        return cls(**d)

    def is_active(self) -> bool:
        now = time.time()
        return self.start_ts <= now <= self.end_ts and self.status == "active"

    def hours_remaining(self) -> float:
        remaining = self.end_ts - time.time()
        return max(0.0, remaining / 3600)

    def urgency_level(self) -> str:
        hrs = self.hours_remaining()
        if hrs < 2:
            return "critical"
        if hrs < 6:
            return "high"
        if hrs < 24:
            return "medium"
        return "low"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class FlashSaleEngine:
    """Manages the full lifecycle of flash sales with AI copywriting support."""

    def __init__(self) -> None:
        self._sales: list[dict] = []
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
                self._sales = data
        except Exception:
            logger.exception("FlashSaleEngine._load failed")
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_REDIS_KEY, self._sales, ttl_seconds=_REDIS_TTL)
        except Exception:
            logger.exception("FlashSaleEngine._save failed")

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    async def create_sale(
        self,
        name: str,
        product_ids: list[str],
        discount_pct: float,
        duration_hours: float = 24.0,
        prices: dict[str, float] | None = None,
    ) -> FlashSale:
        """Create a new flash sale (does not auto-activate it)."""
        await self._load()

        if prices is None:
            prices = {}

        now = time.time()
        sale_prices = {pid: round(price * (1 - discount_pct), 2) for pid, price in prices.items()}

        sale = FlashSale(
            sale_id=str(uuid.uuid4()),
            name=name,
            product_ids=list(product_ids),
            discount_pct=discount_pct,
            original_prices=dict(prices),
            sale_prices=sale_prices,
            start_ts=now,
            end_ts=now + duration_hours * 3600,
            status="planned",
            created_at=now,
        )
        self._sales.append(sale.to_dict())
        await self._save()
        return sale

    async def activate_sale(self, sale_id: str) -> bool:
        """Set sale status to 'active'."""
        await self._load()
        for s in self._sales:
            if s["sale_id"] == sale_id:
                s["status"] = "active"
                await self._save()
                return True
        return False

    async def end_sale(
        self, sale_id: str, revenue: float = 0.0, units: int = 0
    ) -> bool:
        """Mark a sale as ended and record final revenue/units."""
        await self._load()
        for s in self._sales:
            if s["sale_id"] == sale_id:
                s["status"] = "ended"
                s["revenue_generated"] = revenue
                s["units_sold"] = units
                await self._save()
                return True
        return False

    def active_sales(self) -> list[dict]:
        """Return all currently active sales (without triggering a _load)."""
        now = time.time()
        return [
            s for s in self._sales
            if s.get("status") == "active"
            and s.get("start_ts", 0) <= now <= s.get("end_ts", 0)
        ]

    # ------------------------------------------------------------------
    # AI helpers
    # ------------------------------------------------------------------

    async def create_urgency_copy(self, sale: FlashSale) -> str:
        """Generate AI urgency copywriting for the sale."""
        hours = round(sale.hours_remaining(), 1)
        discount = round(sale.discount_pct * 100)
        urgency = sale.urgency_level()

        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel  # type: ignore

            ai = get_ai_client()
            if ai is None:
                raise RuntimeError("no AI client")

            system = (
                "You are an e-commerce copywriter specialising in urgency-driven flash sale messages. "
                "Write compelling, concise copy (1-2 sentences) that drives immediate purchases."
            )
            user = (
                f"Write urgency copy for a flash sale named '{sale.name}'. "
                f"Discount: {discount}% off. Hours remaining: {hours}h. "
                f"Urgency level: {urgency}. Products: {len(sale.product_ids)} items on sale."
            )
            resp = await ai.complete(system, user, AIModel.CREATIVE, 120)
            if resp and resp.success and resp.content:
                return resp.content.strip()
        except Exception:
            logger.debug("AI urgency copy failed, using fallback")

        # Fallback
        return f"Only {hours}h left! Save {discount}% on {sale.name} — grab yours before it's gone!"

    async def plan_optimal_sale(
        self, product_performance: list[dict]
    ) -> dict:
        """
        Given product performance data, recommend which products to put on sale
        and at what discount.

        Each item in product_performance: {product_id, title, views, conversions}
        Low conversion + high views = good sale candidate.
        """
        if not product_performance:
            return {"recommended_product_ids": [], "discount_pct": 0.20, "rationale": "No data"}

        # Heuristic: sort by views descending, then filter low converters
        # conversion_rate = conversions / views
        candidates = []
        for p in product_performance:
            views = p.get("views", 0)
            conversions = p.get("conversions", 0)
            cvr = conversions / views if views > 0 else 0.0
            # High views, low CVR = good candidate
            opportunity_score = views * (1.0 - min(cvr * 10, 1.0))
            candidates.append({**p, "_score": opportunity_score, "_cvr": cvr})

        candidates.sort(key=lambda x: x["_score"], reverse=True)
        top = candidates[:5]
        recommended_ids = [c["product_id"] for c in top]

        # Determine discount: higher opportunity = deeper discount
        avg_cvr = sum(c["_cvr"] for c in top) / max(len(top), 1)
        discount_pct = 0.30 if avg_cvr < 0.01 else 0.20 if avg_cvr < 0.03 else 0.15

        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel  # type: ignore

            ai = get_ai_client()
            if ai is not None:
                product_list = ", ".join(
                    f"{c.get('title', c['product_id'])} (CVR {c['_cvr']:.1%})" for c in top
                )
                system = "You are an e-commerce revenue strategist."
                user = (
                    f"Recommend flash sale strategy for these underperforming products: {product_list}. "
                    f"Suggested discount: {round(discount_pct * 100)}%. "
                    "Give a one-sentence rationale."
                )
                resp = await ai.complete(system, user, AIModel.FAST, 100)
                rationale = (
                    resp.content.strip() if resp and resp.success and resp.content
                    else "High-view, low-conversion products selected for sale."
                )
            else:
                rationale = "High-view, low-conversion products selected for sale."
        except Exception:
            rationale = "High-view, low-conversion products selected for sale."

        return {
            "recommended_product_ids": recommended_ids,
            "discount_pct": discount_pct,
            "rationale": rationale,
            "candidates": [
                {"product_id": c["product_id"], "title": c.get("title", ""), "cvr": round(c["_cvr"], 4)}
                for c in top
            ],
        }

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def sales_analytics(self) -> dict:
        total = len(self._sales)
        total_revenue = sum(s.get("revenue_generated", 0.0) for s in self._sales)
        discounts = [s.get("discount_pct", 0.0) for s in self._sales]
        avg_discount = sum(discounts) / max(len(discounts), 1)
        active_count = len(self.active_sales())
        return {
            "total_sales": total,
            "total_revenue": round(total_revenue, 2),
            "avg_discount": round(avg_discount, 3),
            "active_count": active_count,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine: Optional[FlashSaleEngine] = None


def get_flash_sale_engine() -> FlashSaleEngine:
    global _engine
    if _engine is None:
        _engine = FlashSaleEngine()
    return _engine
