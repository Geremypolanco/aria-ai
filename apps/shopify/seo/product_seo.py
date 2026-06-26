"""
ARIA AI — Shopify Product SEO Optimizer
Phase 12: Drives organic traffic through keyword-optimized product titles,
descriptions, and meta tags.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_KEY = "shopify:seo:v1"
_TTL = 86400 * 30


@dataclass
class ProductSEO:
    seo_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    product_id: str = ""
    product_name: str = ""
    original_title: str = ""
    optimized_title: str = ""
    original_description: str = ""
    optimized_description: str = ""
    meta_title: str = ""
    meta_description: str = ""
    target_keywords: list = field(default_factory=list)
    secondary_keywords: list = field(default_factory=list)
    seo_score: float = 0.0
    estimated_traffic_boost_pct: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "seo_id": self.seo_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "original_title": self.original_title,
            "optimized_title": self.optimized_title,
            "original_description": self.original_description,
            "optimized_description": self.optimized_description,
            "meta_title": self.meta_title,
            "meta_description": self.meta_description,
            "target_keywords": self.target_keywords,
            "secondary_keywords": self.secondary_keywords,
            "seo_score": self.seo_score,
            "estimated_traffic_boost_pct": self.estimated_traffic_boost_pct,
            "created_at": self.created_at,
        }


class ProductSEOOptimizer:
    """
    Shopify product SEO engine.
    State persisted in Redis (key: shopify:seo:v1, TTL 30d).
    """

    def __init__(self) -> None:
        self._optimizations: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._optimizations = data.get("optimizations", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, {"optimizations": self._optimizations[-500:]}, ttl_seconds=_TTL)
        except Exception:
            pass

    def _seo_score(self, title: str, description: str, keywords: list) -> float:
        score = 0.3
        if len(title) >= 30:
            score += 0.15
        if len(title) <= 70:
            score += 0.1
        if len(description) >= 200:
            score += 0.2
        if keywords:
            score += min(len(keywords) * 0.02, 0.15)
        if keywords and any(kw.lower() in title.lower() for kw in keywords):
            score += 0.1
        return min(round(score, 3), 0.95)

    async def optimize_product(
        self,
        product_id: str,
        product_name: str,
        current_title: str,
        current_description: str,
        category: str = "general",
    ) -> ProductSEO:
        """AI rewrites product title, description, and meta tags for SEO."""
        await self._load()
        seo = ProductSEO(
            product_id=product_id,
            product_name=product_name,
            original_title=current_title,
            original_description=current_description,
        )

        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system=(
                    "You are a Shopify SEO expert. Optimize product listings for organic traffic and conversions. "
                    "Write: 1) SEO title (50-70 chars with keyword), "
                    "2) Meta description (≤155 chars, include CTA), "
                    "3) Optimized description (300+ words, keyword-rich). "
                    "Focus on buyer intent keywords."
                ),
                user=(
                    f"Product: {product_name}\nCategory: {category}\n"
                    f"Current title: {current_title}\nCurrent description: {current_description}\n\n"
                    "Generate SEO-optimized version."
                ),
                model=AIModel.STRATEGY,
                max_tokens=800,
            )
            if resp.success:
                lines = [l.strip() for l in resp.content.strip().split("\n") if l.strip()]
                seo.optimized_title = (
                    lines[0].replace("Title:", "").replace("SEO Title:", "").strip()
                )
                if len(seo.optimized_title) > 70:
                    seo.optimized_title = seo.optimized_title[:70]
                seo.optimized_description = resp.content
                seo.meta_description = (
                    f"Shop {product_name}. Best {category} prices. Fast shipping. Order now!"[:155]
                )
        except Exception:
            pass

        if not seo.optimized_title:
            seo.optimized_title = f"Buy {product_name} — Premium {category.title()} | Best Price"[
                :70
            ]
        if not seo.optimized_description:
            seo.optimized_description = (
                f"Discover {product_name} — the premium {category} solution designed for results. "
                f"Shop our collection and experience the difference quality makes. "
                f"Fast shipping, easy returns, and unbeatable prices on all {category} products."
            )
        if not seo.meta_description:
            seo.meta_description = (
                f"Shop {product_name}. Best {category} prices. Fast shipping. Order now!"[:155]
            )

        seo.meta_title = seo.optimized_title
        seo.target_keywords = [
            product_name.lower(),
            f"buy {product_name.lower()}",
            f"best {product_name.lower()}",
            f"{product_name.lower()} online",
            category.lower(),
        ]
        seo.secondary_keywords = [
            f"{product_name} review",
            f"{product_name} price",
            f"cheap {product_name}",
            f"{product_name} deal",
            f"{product_name} sale",
            f"top {category}",
            f"best {category} 2024",
            f"{category} online",
            f"buy {category}",
            f"{product_name} discount",
        ]
        seo.seo_score = self._seo_score(
            seo.optimized_title, seo.optimized_description, seo.target_keywords
        )
        seo.estimated_traffic_boost_pct = round(max(0.0, (seo.seo_score - 0.3) * 150), 1)

        self._optimizations.append(seo.to_dict())
        await self._save()
        return seo

    async def bulk_optimize(self, products: list[dict]) -> list[ProductSEO]:
        """Optimize multiple products in sequence."""
        results = []
        for p in products:
            opt = await self.optimize_product(
                p.get("product_id", str(uuid.uuid4())[:8]),
                p.get("name", "Product"),
                p.get("title", ""),
                p.get("description", ""),
                p.get("category", "general"),
            )
            results.append(opt)
        return results

    async def audit_keywords(self, niche: str) -> dict:
        """AI identifies high-traffic commercial intent keywords for a niche."""
        ai = get_ai_client()
        content = ""
        try:
            resp = await ai.complete(
                system="You are a Shopify SEO analyst. Identify high-traffic, low-competition keywords for a product niche.",
                user=(
                    f"Niche: {niche}. "
                    "List 20 product keywords with search intent (buy/compare/learn). "
                    "Focus on commercial and transactional intent."
                ),
                model=AIModel.STRATEGY,
                max_tokens=500,
            )
            content = resp.content if resp.success else ""
        except Exception:
            pass

        return {
            "niche": niche,
            "commercial_keywords": [
                f"buy {niche}",
                f"best {niche}",
                f"{niche} for sale",
                f"cheap {niche}",
                f"{niche} online",
            ],
            "comparison_keywords": [
                f"{niche} review",
                f"best {niche} 2024",
                f"{niche} vs",
                f"top {niche} brands",
            ],
            "long_tail": [
                f"where to buy {niche}",
                f"best {niche} for beginners",
                f"affordable {niche}",
            ],
            "analysis": content,
        }

    def seo_stats(self) -> dict:
        if not self._optimizations:
            return {"total_optimized": 0, "avg_seo_score": 0.0, "avg_traffic_boost_pct": 0.0}
        scores = [o.get("seo_score", 0.0) for o in self._optimizations]
        boosts = [o.get("estimated_traffic_boost_pct", 0.0) for o in self._optimizations]
        return {
            "total_optimized": len(self._optimizations),
            "avg_seo_score": round(sum(scores) / len(scores), 3),
            "avg_traffic_boost_pct": round(sum(boosts) / len(boosts), 1),
        }

    def recent_optimizations(self, limit: int = 10) -> list[dict]:
        return sorted(self._optimizations, key=lambda x: x.get("created_at", 0), reverse=True)[
            :limit
        ]


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: ProductSEOOptimizer | None = None


def get_product_seo_optimizer() -> ProductSEOOptimizer:
    global _instance
    if _instance is None:
        _instance = ProductSEOOptimizer()
    return _instance
