"""
Autonomous Shopify commerce operator.

Wraps ShopifyEngine with AI-driven intelligence for catalog analysis,
listing optimization, and autonomous improvement cycles.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ProductPerformance:
    product_id: str
    title: str
    views: int = 0
    add_to_carts: int = 0
    purchases: int = 0
    revenue_usd: float = 0.0
    seo_score: float = 0.0
    last_analyzed: float = 0.0

    @property
    def conversion_rate(self) -> float:
        """Purchases / views, 0 if no views."""
        if self.views == 0:
            return 0.0
        return self.purchases / self.views

    @property
    def ctr(self) -> float:
        """Add-to-carts / views click-through rate, 0 if no views."""
        if self.views == 0:
            return 0.0
        return self.add_to_carts / self.views


@dataclass
class CatalogOpportunity:
    opportunity_type: str
    product_id: str
    title: str
    impact_score: float
    recommendation: str


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

_MOCK_PRODUCTS = [
    {
        "id": "mock-001",
        "title": "Sample Product A",
        "body_html": "",
        "tags": "",
        "images": [],
        "variants": [{"price": "29.99", "inventory_quantity": 5}],
    },
    {
        "id": "mock-002",
        "title": "Sample Product B",
        "body_html": "<p>A great product for everyday use with excellent quality.</p>",
        "tags": "home,lifestyle,gift",
        "images": [{"src": "https://example.com/img.jpg", "alt": "Product B"}],
        "variants": [{"price": "49.99", "inventory_quantity": 0}],
    },
]


def _score_product(product: dict) -> float:
    """Return a 0–100 SEO/completeness score for a raw product dict."""
    score = 0.0

    title = product.get("title", "")
    if title and 20 <= len(title) <= 70:
        score += 25.0
    elif title:
        score += 10.0

    body = product.get("body_html", "") or ""
    if len(body) > 200:
        score += 25.0
    elif len(body) > 50:
        score += 10.0

    tags = product.get("tags", "") or ""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    if len(tag_list) >= 5:
        score += 20.0
    elif len(tag_list) >= 2:
        score += 10.0

    images = product.get("images", []) or []
    if images:
        score += 20.0
        alts = sum(1 for img in images if img.get("alt"))
        score += min(alts * 5.0, 10.0)

    return min(score, 100.0)


class ShopifyOperator:
    """Autonomous Shopify commerce operator."""

    CACHE_KEY = "shopify:performance:v1"
    CACHE_TTL = 3600  # 1 hour

    def __init__(self) -> None:
        self._engine = None
        self._performance_cache: dict[str, ProductPerformance] = {}
        self._last_cycle_ts: float = 0.0
        self._total_products: int = 0

        try:
            from apps.core.config_pkg import settings  # type: ignore

            shop = getattr(settings, "SHOPIFY_SHOP_NAME", "")
            token = getattr(settings, "SHOPIFY_ACCESS_TOKEN", "")
            if shop and token:
                from apps.core.integrations.shopify_engine import ShopifyEngine  # type: ignore

                self._engine = ShopifyEngine(
                    shop_name=shop, access_token=token
                )
                logger.info("ShopifyOperator: engine initialised for %s", shop)
            else:
                logger.info(
                    "ShopifyOperator: no credentials — running in mock mode"
                )
        except Exception:
            logger.exception("ShopifyOperator: failed to initialise engine")

        # Best-effort: load cached performance data
        # (can't await in __init__; callers should call analyze_catalog first)

    # ------------------------------------------------------------------
    # Core async methods
    # ------------------------------------------------------------------

    async def _load_cached_performance(self) -> None:
        try:
            from apps.core.memory.redis_client import get_cache  # type: ignore

            cache = get_cache()
            data = await cache.get(self.CACHE_KEY)
            if data and isinstance(data, dict):
                for pid, pd in data.items():
                    self._performance_cache[pid] = ProductPerformance(**pd)
        except Exception:
            logger.debug("ShopifyOperator: could not load performance cache")

    async def _save_cached_performance(self) -> None:
        try:
            from apps.core.memory.redis_client import get_cache  # type: ignore

            cache = get_cache()
            serializable = {
                pid: {
                    "product_id": pp.product_id,
                    "title": pp.title,
                    "views": pp.views,
                    "add_to_carts": pp.add_to_carts,
                    "purchases": pp.purchases,
                    "revenue_usd": pp.revenue_usd,
                    "seo_score": pp.seo_score,
                    "last_analyzed": pp.last_analyzed,
                }
                for pid, pp in self._performance_cache.items()
            }
            await cache.set(self.CACHE_KEY, serializable, ttl_seconds=self.CACHE_TTL)
        except Exception:
            logger.debug("ShopifyOperator: could not save performance cache")

    async def analyze_catalog(self) -> list[ProductPerformance]:
        """
        Fetch all products and score each for SEO/completeness.

        Returns a list of ProductPerformance ordered by seo_score descending.
        Falls back to mock data when no engine is available.
        """
        products: list[dict] = []

        if self._engine is not None:
            try:
                products = await self._engine.get_all_products() or []
            except Exception:
                logger.exception("ShopifyOperator.analyze_catalog: engine error")
                products = []

        if not products:
            products = _MOCK_PRODUCTS

        results: list[ProductPerformance] = []
        now = time.time()

        for p in products:
            pid = str(p.get("id", ""))
            title = p.get("title", "Unknown")
            seo = _score_product(p)

            # Merge with any cached performance data
            cached = self._performance_cache.get(pid)
            perf = ProductPerformance(
                product_id=pid,
                title=title,
                views=cached.views if cached else 0,
                add_to_carts=cached.add_to_carts if cached else 0,
                purchases=cached.purchases if cached else 0,
                revenue_usd=cached.revenue_usd if cached else 0.0,
                seo_score=seo,
                last_analyzed=now,
            )
            self._performance_cache[pid] = perf
            results.append(perf)

        self._total_products = len(results)
        await self._save_cached_performance()

        results.sort(key=lambda x: x.seo_score, reverse=True)
        return results

    async def optimize_listing(
        self, product_id: str, product_data: dict
    ) -> bool:
        """
        Use AI to improve a product title and description, then push the
        update via the engine.  Returns True on success.
        """
        if self._engine is None:
            logger.info(
                "ShopifyOperator.optimize_listing: no engine, skipping update"
            )
            return False

        try:
            title = product_data.get("title", "")
            category = product_data.get("product_type", "general")
            features_raw = product_data.get("tags", "")
            features = [t.strip() for t in features_raw.split(",") if t.strip()]

            new_description = await self.generate_seo_description(
                title, category, features
            )

            updated = dict(product_data)
            updated["body_html"] = new_description

            await self._engine.update_product_listing(product_id, updated)
            logger.info(
                "ShopifyOperator.optimize_listing: updated product %s", product_id
            )
            return True
        except Exception:
            logger.exception(
                "ShopifyOperator.optimize_listing: failed for %s", product_id
            )
            return False

    async def generate_seo_description(
        self,
        product_title: str,
        category: str,
        features: list[str],
    ) -> str:
        """
        Use AI to write a 200–300 word SEO-optimised product description.
        Returns a plain-text fallback when AI is unavailable.
        """
        fallback = (
            f"{product_title} — a quality {category} product. "
            + (
                "Features include: " + ", ".join(features) + "."
                if features
                else ""
            )
        )

        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel  # type: ignore

            ai = await get_ai_client()
            features_str = ", ".join(features) if features else "various useful features"
            prompt = (
                f"Write a compelling, SEO-optimised product description of 200–300 words "
                f"for a {category} product called '{product_title}'. "
                f"Key features: {features_str}. "
                "Use natural language, include relevant keywords organically, "
                "and end with a clear call-to-action. Return plain text only."
            )
            result = await ai.complete(prompt, model=AIModel.DEFAULT)
            return result.strip() if result else fallback
        except Exception:
            logger.debug(
                "ShopifyOperator.generate_seo_description: AI unavailable, using fallback"
            )
            return fallback

    async def pricing_analysis(self) -> dict[str, Any]:
        """
        Return basic pricing insights derived from the live (or mock) catalog.
        """
        products: list[dict] = []

        if self._engine is not None:
            try:
                products = await self._engine.get_all_products() or []
            except Exception:
                logger.exception("ShopifyOperator.pricing_analysis: engine error")

        if not products:
            products = _MOCK_PRODUCTS

        prices: list[float] = []
        for p in products:
            for variant in p.get("variants", []):
                try:
                    prices.append(float(variant.get("price", 0)))
                except (TypeError, ValueError):
                    pass

        if not prices:
            return {
                "avg_price": 0.0,
                "price_range": {"min": 0.0, "max": 0.0},
                "under_priced_products": [],
                "over_priced_products": [],
            }

        avg = sum(prices) / len(prices)
        lower_bound = avg * 0.5
        upper_bound = avg * 2.0

        under_priced: list[dict] = []
        over_priced: list[dict] = []

        for p in products:
            for variant in p.get("variants", []):
                try:
                    price = float(variant.get("price", 0))
                except (TypeError, ValueError):
                    continue
                entry = {"product_id": str(p.get("id", "")), "title": p.get("title", ""), "price": price}
                if price < lower_bound:
                    under_priced.append(entry)
                elif price > upper_bound:
                    over_priced.append(entry)

        return {
            "avg_price": round(avg, 2),
            "price_range": {"min": round(min(prices), 2), "max": round(max(prices), 2)},
            "under_priced_products": under_priced,
            "over_priced_products": over_priced,
        }

    async def identify_opportunities(self) -> list[CatalogOpportunity]:
        """
        Scan the catalog for improvement opportunities.
        Returns opportunities ranked by impact_score descending.
        """
        products: list[dict] = []

        if self._engine is not None:
            try:
                products = await self._engine.get_all_products() or []
            except Exception:
                logger.exception(
                    "ShopifyOperator.identify_opportunities: engine error"
                )

        if not products:
            products = _MOCK_PRODUCTS

        opportunities: list[CatalogOpportunity] = []

        for p in products:
            pid = str(p.get("id", ""))
            title = p.get("title", "Unknown")
            body = p.get("body_html", "") or ""
            tags = p.get("tags", "") or ""
            images = p.get("images", []) or []
            inventory = sum(
                int(v.get("inventory_quantity", 0) or 0)
                for v in p.get("variants", [])
            )

            if not body.strip():
                opportunities.append(
                    CatalogOpportunity(
                        opportunity_type="seo_optimize",
                        product_id=pid,
                        title=title,
                        impact_score=9.0,
                        recommendation="Add a detailed product description to improve SEO and conversion.",
                    )
                )

            if not tags.strip():
                opportunities.append(
                    CatalogOpportunity(
                        opportunity_type="add_tags",
                        product_id=pid,
                        title=title,
                        impact_score=6.0,
                        recommendation="Add relevant tags to improve discoverability and search ranking.",
                    )
                )

            if not images:
                opportunities.append(
                    CatalogOpportunity(
                        opportunity_type="add_images",
                        product_id=pid,
                        title=title,
                        impact_score=8.5,
                        recommendation="Upload product images — listings with images convert significantly better.",
                    )
                )

            if 0 <= inventory <= 3:
                opportunities.append(
                    CatalogOpportunity(
                        opportunity_type="restock_alert",
                        product_id=pid,
                        title=title,
                        impact_score=7.0,
                        recommendation=f"Low inventory ({inventory} units). Restock to avoid lost sales.",
                    )
                )

        opportunities.sort(key=lambda x: x.impact_score, reverse=True)
        return opportunities

    async def run_autonomous_cycle(self) -> dict[str, Any]:
        """
        Full autonomous improvement cycle:
        1. Analyze catalog
        2. Identify opportunities
        3. Act on top 3 opportunities
        Returns a summary dict.
        """
        actions_taken: list[str] = []
        products_updated: list[str] = []

        performances = await self.analyze_catalog()
        opportunities = await self.identify_opportunities()

        top_opportunities = opportunities[:3]

        for opp in top_opportunities:
            try:
                if opp.opportunity_type == "seo_optimize" and self._engine is not None:
                    # Find the raw product data to pass to optimize_listing
                    raw_products: list[dict] = []
                    try:
                        raw_products = await self._engine.get_all_products() or []
                    except Exception:
                        pass
                    product_data = next(
                        (p for p in raw_products if str(p.get("id", "")) == opp.product_id),
                        {"title": opp.title, "product_type": "general", "tags": ""},
                    )
                    success = await self.optimize_listing(opp.product_id, product_data)
                    if success:
                        actions_taken.append(
                            f"seo_optimize:{opp.product_id}"
                        )
                        products_updated.append(opp.product_id)
                else:
                    # Log the opportunity without automated action
                    actions_taken.append(
                        f"flagged:{opp.opportunity_type}:{opp.product_id}"
                    )
            except Exception:
                logger.exception(
                    "ShopifyOperator.run_autonomous_cycle: error on opportunity %s",
                    opp.opportunity_type,
                )

        self._last_cycle_ts = time.time()

        return {
            "actions_taken": actions_taken,
            "opportunities_found": len(opportunities),
            "products_updated": products_updated,
            "total_products_analyzed": len(performances),
            "cycle_ts": self._last_cycle_ts,
        }

    def summary(self) -> dict[str, Any]:
        """Return a high-level health summary of the catalog."""
        if not self._performance_cache:
            avg_seo = 0.0
            opt_opportunities = 0
        else:
            scores = [pp.seo_score for pp in self._performance_cache.values()]
            avg_seo = sum(scores) / len(scores)
            opt_opportunities = sum(1 for s in scores if s < 50.0)

        health_label = (
            "good" if avg_seo >= 70 else "fair" if avg_seo >= 40 else "needs_work"
        )

        return {
            "catalog_health": health_label,
            "avg_seo_score": round(avg_seo, 1),
            "total_products": self._total_products,
            "optimization_opportunities": opt_opportunities,
            "last_cycle_ts": self._last_cycle_ts,
        }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_operator_instance: ShopifyOperator | None = None


def get_shopify_operator() -> ShopifyOperator:
    """Return the shared ShopifyOperator singleton."""
    global _operator_instance
    if _operator_instance is None:
        _operator_instance = ShopifyOperator()
    return _operator_instance
