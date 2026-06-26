"""
Dynamic product bundle creator — generates complementary, quantity,
starter and premium bundles with AI-driven naming and descriptions.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache

logger = logging.getLogger(__name__)

_REDIS_KEY = "shopify:bundles:v1"
_REDIS_TTL = 86400 * 60  # 60 days

_VALID_BUNDLE_TYPES = {"complementary", "quantity", "starter", "premium"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ProductBundle:
    bundle_id: str
    name: str
    product_ids: list[str]
    product_titles: list[str]
    individual_total: float
    bundle_price: float
    savings: float
    savings_pct: float
    bundle_type: str  # "complementary" | "quantity" | "starter" | "premium"
    description: str
    cta: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "bundle_id": self.bundle_id,
            "name": self.name,
            "product_ids": self.product_ids,
            "product_titles": self.product_titles,
            "individual_total": self.individual_total,
            "bundle_price": self.bundle_price,
            "savings": self.savings,
            "savings_pct": self.savings_pct,
            "bundle_type": self.bundle_type,
            "description": self.description,
            "cta": self.cta,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ProductBundle:
        return cls(**d)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class BundleGenerator:
    """Creates and manages product bundles with AI-generated copy."""

    def __init__(self) -> None:
        self._bundles: list[dict] = []
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
                self._bundles = data
        except Exception:
            logger.exception("BundleGenerator._load failed")
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_REDIS_KEY, self._bundles, ttl_seconds=_REDIS_TTL)
        except Exception:
            logger.exception("BundleGenerator._save failed")

    # ------------------------------------------------------------------
    # AI helpers
    # ------------------------------------------------------------------

    async def _ai_bundle_copy(
        self,
        products: list[dict],
        bundle_type: str,
        individual_total: float,
        bundle_price: float,
    ) -> tuple[str, str, str]:
        """Return (name, description, cta) from AI or fallback."""
        titles = [p.get("title", p.get("id", "Product")) for p in products]
        savings = round(individual_total - bundle_price, 2)
        savings_pct = round((savings / individual_total) * 100) if individual_total > 0 else 0

        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client  # type: ignore

            ai = get_ai_client()
            if ai is None:
                raise RuntimeError("no AI client")

            system = (
                "You are an e-commerce copywriter. "
                "Generate a bundle name, short description (1 sentence) and CTA (4-6 words) "
                "for the product bundle. Respond in this exact format:\n"
                "NAME: <bundle name>\nDESC: <description>\nCTA: <call to action>"
            )
            user = (
                f"Bundle type: {bundle_type}. "
                f"Products: {', '.join(titles)}. "
                f"Save ${savings} ({savings_pct}% off) with this bundle."
            )
            resp = await ai.complete(system, user, AIModel.CREATIVE, 150)
            if resp and resp.success and resp.content:
                lines = resp.content.strip().splitlines()
                name = desc = cta = ""
                for line in lines:
                    if line.startswith("NAME:"):
                        name = line[5:].strip()
                    elif line.startswith("DESC:"):
                        desc = line[5:].strip()
                    elif line.startswith("CTA:"):
                        cta = line[4:].strip()
                if name:
                    return name, desc, cta
        except Exception:
            logger.debug("AI bundle copy failed, using fallback")

        # Fallback
        if bundle_type == "starter":
            name = f"Starter {titles[0]} Kit" if titles else "Starter Kit"
        elif bundle_type == "premium":
            name = f"Premium {titles[0]} Collection" if titles else "Premium Collection"
        elif bundle_type == "quantity":
            name = f"{titles[0]} Value Pack" if titles else "Value Pack"
        else:
            name = f"Complete {titles[0]} Bundle" if titles else "Complete Bundle"
        desc = f"Get {len(products)} products together and save ${savings}."
        cta = f"Bundle & Save {savings_pct}%"
        return name, desc, cta

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    async def create_bundle(
        self,
        products: list[dict],
        bundle_type: str = "complementary",
        discount_pct: float = 0.15,
    ) -> ProductBundle:
        """
        Create a bundle from a list of {id, title, price} product dicts.
        AI generates the name, description and CTA.
        """
        await self._load()

        if bundle_type not in _VALID_BUNDLE_TYPES:
            bundle_type = "complementary"

        individual_total = round(sum(float(p.get("price", 0)) for p in products), 2)
        bundle_price = round(individual_total * (1 - discount_pct), 2)
        savings = round(individual_total - bundle_price, 2)
        savings_pct = round((savings / individual_total) * 100, 2) if individual_total > 0 else 0.0

        name, description, cta = await self._ai_bundle_copy(
            products, bundle_type, individual_total, bundle_price
        )

        bundle = ProductBundle(
            bundle_id=str(uuid.uuid4()),
            name=name,
            product_ids=[p.get("id", "") for p in products],
            product_titles=[p.get("title", "") for p in products],
            individual_total=individual_total,
            bundle_price=bundle_price,
            savings=savings,
            savings_pct=savings_pct,
            bundle_type=bundle_type,
            description=description,
            cta=cta,
            created_at=time.time(),
        )
        self._bundles.append(bundle.to_dict())
        await self._save()
        return bundle

    async def generate_smart_bundles(
        self, catalog: list[dict], count: int = 5
    ) -> list[ProductBundle]:
        """
        Auto-generate bundles from a product catalog.
        catalog items: {id, title, price, category}
        Groups products by category and creates "Complete [Category] Kit" bundles.
        """
        await self._load()

        if not catalog:
            return []

        # Group by category
        by_category: dict[str, list[dict]] = {}
        for product in catalog:
            cat = product.get("category", "General")
            by_category.setdefault(cat, []).append(product)

        bundles: list[ProductBundle] = []
        for cat, products in by_category.items():
            if len(bundles) >= count:
                break
            if len(products) < 2:
                continue
            # Take up to 3 products per bundle
            group = products[:3]
            bundle = await self.create_bundle(group, bundle_type="complementary")
            bundles.append(bundle)

        # If we need more bundles, try AI-driven grouping with remaining catalog
        if len(bundles) < count and len(catalog) >= 2:
            try:
                from apps.core.tools.ai_client import AIModel, get_ai_client  # type: ignore

                ai = get_ai_client()
                if ai is not None:
                    product_list = "; ".join(
                        f"{p.get('id')}:{p.get('title')} (${p.get('price', 0)})"
                        for p in catalog[:20]
                    )
                    system = "You are an e-commerce bundling expert."
                    user = (
                        f"From these products, suggest {count - len(bundles)} complementary product groups "
                        f"(2-3 products each) for bundles. Products: {product_list}. "
                        "List each group as comma-separated IDs on a new line."
                    )
                    resp = await ai.complete(system, user, AIModel.STRATEGY, 300)
                    if resp and resp.success and resp.content:
                        id_lookup = {p.get("id"): p for p in catalog}
                        for line in resp.content.strip().splitlines():
                            if len(bundles) >= count:
                                break
                            ids = [x.strip() for x in line.split(",") if x.strip()]
                            group = [id_lookup[i] for i in ids if i in id_lookup]
                            if len(group) >= 2:
                                bundle = await self.create_bundle(
                                    group, bundle_type="complementary"
                                )
                                bundles.append(bundle)
            except Exception:
                logger.debug("AI smart bundle generation failed")

        return bundles[:count]

    async def aov_optimization_bundles(
        self, avg_order_value: float, catalog: list[dict]
    ) -> list[ProductBundle]:
        """
        Create bundles targeting 1.5x current AOV.
        Returns top 3 bundle recommendations.
        """
        await self._load()

        target_value = avg_order_value * 1.5
        bundles: list[ProductBundle] = []

        if not catalog:
            return []

        # Sort catalog by price descending so we can build toward target AOV
        sorted_catalog = sorted(catalog, key=lambda p: float(p.get("price", 0)), reverse=True)

        # Try to build bundles that total close to target_value
        for i in range(min(3, len(sorted_catalog))):
            group = []
            running_total = 0.0
            for product in sorted_catalog:
                price = float(product.get("price", 0))
                if running_total + price <= target_value * 1.2:
                    group.append(product)
                    running_total += price
                if len(group) >= 3:
                    break

            if len(group) >= 2:
                bundle_type = "starter" if i == 0 else "complementary" if i == 1 else "premium"
                bundle = await self.create_bundle(
                    group, bundle_type=bundle_type, discount_pct=0.10 + i * 0.05
                )
                bundles.append(bundle)

            # Shift catalog for next bundle variation
            sorted_catalog = sorted_catalog[1:] + sorted_catalog[:1]

        return bundles[:3]

    def active_bundles(self) -> list[dict]:
        """Return all stored bundles."""
        return list(self._bundles)

    def bundle_stats(self) -> dict:
        """Aggregate stats across all bundles."""
        total = len(self._bundles)
        if total == 0:
            return {
                "total_bundles": 0,
                "avg_savings_pct": 0.0,
                "by_type": {},
            }

        avg_savings = sum(b.get("savings_pct", 0.0) for b in self._bundles) / total
        by_type: dict[str, int] = {}
        for b in self._bundles:
            t = b.get("bundle_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        return {
            "total_bundles": total,
            "avg_savings_pct": round(avg_savings, 2),
            "by_type": by_type,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_generator: BundleGenerator | None = None


def get_bundle_generator() -> BundleGenerator:
    global _generator
    if _generator is None:
        _generator = BundleGenerator()
    return _generator
