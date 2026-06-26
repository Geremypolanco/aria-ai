"""
Product recommendation engine — collaborative/content-based filtering,
upsell and cross-sell recommendations with context awareness.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_REDIS_KEY = "shopify:recommendations:v1"
_REDIS_TTL = 86400 * 30  # 30 days

_VALID_CONTEXTS = {"cart", "product", "homepage", "post_purchase"}
_VALID_STRATEGIES = {"collaborative", "content", "trending", "upsell"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class RecommendationSet:
    user_id: str
    context: str  # "cart" | "product" | "homepage" | "post_purchase"
    recommended_ids: list[str]
    recommended_titles: list[str]
    scores: list[float]
    strategy: str  # "collaborative" | "content" | "trending" | "upsell"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "context": self.context,
            "recommended_ids": self.recommended_ids,
            "recommended_titles": self.recommended_titles,
            "scores": self.scores,
            "strategy": self.strategy,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RecommendationSet:
        return cls(**d)


# ---------------------------------------------------------------------------
# Recommender
# ---------------------------------------------------------------------------


class ProductRecommender:
    """Tracks interactions and returns contextualised product recommendations."""

    def __init__(self) -> None:
        # user_id -> list of product_ids interacted with
        self._interaction_data: dict[str, list[str]] = {}
        self._loaded = False
        # Lightweight popularity counter: product_id -> interaction count
        self._popularity: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            from apps.core.memory.redis_client import get_cache  # type: ignore

            cache = get_cache()
            data = await cache.get(_REDIS_KEY)
            if data and isinstance(data, dict):
                self._interaction_data = data.get("interactions", {})
                self._popularity = data.get("popularity", {})
        except Exception:
            logger.exception("ProductRecommender._load failed")
        self._loaded = True

    async def _save(self) -> None:
        try:
            from apps.core.memory.redis_client import get_cache  # type: ignore

            cache = get_cache()
            await cache.set(
                _REDIS_KEY,
                {"interactions": self._interaction_data, "popularity": self._popularity},
                ttl_seconds=_REDIS_TTL,
            )
        except Exception:
            logger.exception("ProductRecommender._save failed")

    # ------------------------------------------------------------------
    # Interaction tracking
    # ------------------------------------------------------------------

    async def record_interaction(
        self, user_id: str, product_id: str, interaction_type: str = "view"
    ) -> None:
        """Track a user-product interaction (view, add_to_cart, purchase, etc.)."""
        await self._load()

        history = self._interaction_data.setdefault(user_id, [])
        if product_id not in history:
            history.append(product_id)
        # Cap history per user
        if len(history) > 100:
            self._interaction_data[user_id] = history[-100:]

        # Update popularity (weighted by interaction type)
        weight = {"view": 1, "add_to_cart": 3, "purchase": 5}.get(interaction_type, 1)
        self._popularity[product_id] = self._popularity.get(product_id, 0) + weight

        await self._save()

    # ------------------------------------------------------------------
    # Recommendation logic
    # ------------------------------------------------------------------

    async def recommend(
        self,
        user_id: str,
        context: str,
        catalog: list[dict],
        current_product_id: str = "",
        limit: int = 5,
    ) -> RecommendationSet:
        """
        Return contextualised recommendations.
        catalog items: {id, title, price, category, tags}
        """
        await self._load()

        if context not in _VALID_CONTEXTS:
            context = "homepage"

        user_history = self._interaction_data.get(user_id, [])
        strategy = "trending"
        scored: list[tuple[dict, float]] = []

        if user_history and catalog:
            strategy = "content"
            # Content-based: find categories/tags of viewed products
            viewed_ids = set(user_history)
            viewed_products = [p for p in catalog if p.get("id") in viewed_ids]
            viewed_categories = {p.get("category", "") for p in viewed_products}
            viewed_tags: set[str] = set()
            for p in viewed_products:
                tags = p.get("tags", [])
                if isinstance(tags, list):
                    viewed_tags.update(tags)
                elif isinstance(tags, str):
                    viewed_tags.update(t.strip() for t in tags.split(","))

            for product in catalog:
                pid = product.get("id", "")
                if pid in viewed_ids or pid == current_product_id:
                    continue
                score = 0.0
                cat = product.get("category", "")
                if cat and cat in viewed_categories:
                    score += 0.5
                ptags = product.get("tags", [])
                if isinstance(ptags, str):
                    ptags = [t.strip() for t in ptags.split(",")]
                overlap = viewed_tags & set(ptags)
                score += len(overlap) * 0.1
                # Popularity boost
                pop = self._popularity.get(pid, 0)
                score += min(pop * 0.01, 0.3)
                scored.append((product, round(min(score, 1.0), 3)))

        else:
            strategy = "trending"
            for product in catalog:
                pid = product.get("id", "")
                if pid == current_product_id:
                    continue
                pop = self._popularity.get(pid, 0)
                score = round(min(pop * 0.01, 1.0), 3)
                scored.append((product, score))

        # Context-specific adjustments
        if context == "post_purchase":
            strategy = "content"
            # Boost consumables and accessories
            consumable_keywords = {
                "refill",
                "accessory",
                "accessories",
                "consumable",
                "replacement",
                "add-on",
            }
            boosted: list[tuple[dict, float]] = []
            for product, score in scored:
                tags = product.get("tags", [])
                if isinstance(tags, str):
                    tags = [t.strip().lower() for t in tags.split(",")]
                else:
                    tags = [t.lower() for t in tags]
                tag_set = set(tags)
                title_lower = product.get("title", "").lower()
                if tag_set & consumable_keywords or any(
                    k in title_lower for k in consumable_keywords
                ):
                    score = min(score + 0.3, 1.0)
                boosted.append((product, score))
            scored = boosted

        elif context == "cart":
            # Boost complementary items (different categories)
            cart_categories: set[str] = set()
            if current_product_id:
                for p in catalog:
                    if p.get("id") == current_product_id:
                        cart_categories.add(p.get("category", ""))
            boosted = []
            for product, score in scored:
                if product.get("category", "") not in cart_categories:
                    score = min(score + 0.2, 1.0)
                boosted.append((product, score))
            scored = boosted

        # Sort and take top-N
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:limit]

        return RecommendationSet(
            user_id=user_id,
            context=context,
            recommended_ids=[p.get("id", "") for p, _ in top],
            recommended_titles=[p.get("title", "") for p, _ in top],
            scores=[s for _, s in top],
            strategy=strategy,
            created_at=time.time(),
        )

    async def upsell_recommendations(
        self, product_id: str, product_price: float, catalog: list[dict]
    ) -> list[dict]:
        """Recommend products in the 1.5–2x price range of current product."""
        await self._load()
        low = product_price * 1.5
        high = product_price * 2.0
        candidates = [
            p
            for p in catalog
            if p.get("id") != product_id and low <= float(p.get("price", 0)) <= high
        ]
        # Sort by popularity
        candidates.sort(key=lambda p: self._popularity.get(p.get("id", ""), 0), reverse=True)
        return candidates[:5]

    async def cross_sell_recommendations(
        self, cart_items: list[dict], catalog: list[dict]
    ) -> list[dict]:
        """Recommend items that complement the cart (different categories)."""
        await self._load()
        cart_ids = {item.get("id", "") for item in cart_items}
        cart_categories = {item.get("category", "") for item in cart_items}

        candidates = [
            p
            for p in catalog
            if p.get("id") not in cart_ids and p.get("category", "") not in cart_categories
        ]
        # Sort by popularity
        candidates.sort(key=lambda p: self._popularity.get(p.get("id", ""), 0), reverse=True)
        return candidates[:5]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def recommendation_stats(self) -> dict:
        users_tracked = len(self._interaction_data)
        total_interactions = sum(len(v) for v in self._interaction_data.values())
        top_products = sorted(self._popularity.items(), key=lambda x: x[1], reverse=True)[:5]
        return {
            "total_recommendations": total_interactions,
            "users_tracked": users_tracked,
            "top_recommended_products": [
                {"product_id": pid, "interaction_count": count} for pid, count in top_products
            ],
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_recommender: ProductRecommender | None = None


def get_product_recommender() -> ProductRecommender:
    global _recommender
    if _recommender is None:
        _recommender = ProductRecommender()
    return _recommender
