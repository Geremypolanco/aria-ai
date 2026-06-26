"""
ARIA AI — Shopify Funnel Engine
Phase 12: Upsell flows, abandoned cart sequences, landing pages, checkout optimization.
Drives AOV, conversion rate, and repeat purchase rate.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_KEY = "shopify:funnels:v1"
_TTL = 86400 * 30


@dataclass
class ShopifyFunnel:
    funnel_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    funnel_type: str = ""  # "upsell", "abandoned_cart", "landing", "cross_sell", "post_purchase"
    product_name: str = ""
    stages: list = field(default_factory=list)
    headline: str = ""
    body_copy: str = ""
    cta: str = ""
    discount_pct: float = 0.0
    expected_cvr_pct: float = 0.0
    expected_aov_lift_pct: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "funnel_id": self.funnel_id,
            "funnel_type": self.funnel_type,
            "product_name": self.product_name,
            "stages": self.stages,
            "headline": self.headline,
            "body_copy": self.body_copy,
            "cta": self.cta,
            "discount_pct": self.discount_pct,
            "expected_cvr_pct": self.expected_cvr_pct,
            "expected_aov_lift_pct": self.expected_aov_lift_pct,
            "created_at": self.created_at,
        }


@dataclass
class UpsellOffer:
    offer_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    original_product: str = ""
    upsell_product: str = ""
    original_price: float = 0.0
    upsell_price: float = 0.0
    headline: str = ""
    reason: str = ""
    urgency_trigger: str = ""
    acceptance_rate_pct: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "offer_id": self.offer_id,
            "original_product": self.original_product,
            "upsell_product": self.upsell_product,
            "original_price": self.original_price,
            "upsell_price": self.upsell_price,
            "headline": self.headline,
            "reason": self.reason,
            "urgency_trigger": self.urgency_trigger,
            "acceptance_rate_pct": self.acceptance_rate_pct,
            "created_at": self.created_at,
        }


class ShopifyFunnelEngine:
    """
    Shopify conversion funnel engine.
    State persisted in Redis (key: shopify:funnels:v1, TTL 30d).
    """

    def __init__(self) -> None:
        self._funnels: list[dict] = []
        self._upsells: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._funnels = data.get("funnels", [])
                    self._upsells = data.get("upsells", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _KEY,
                {"funnels": self._funnels[-300:], "upsells": self._upsells[-300:]},
                ttl_seconds=_TTL,
            )
        except Exception:
            pass

    async def create_upsell_flow(
        self,
        original_product: str,
        original_price: float,
        upsell_product: str,
        upsell_price: float,
    ) -> UpsellOffer:
        """AI generates persuasive upsell offer to increase AOV."""
        await self._load()
        offer = UpsellOffer(
            original_product=original_product,
            upsell_product=upsell_product,
            original_price=original_price,
            upsell_price=upsell_price,
        )

        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system=(
                    "You are a Shopify conversion expert. Create a compelling upsell offer. "
                    "Include: headline (curiosity + benefit), reason to upgrade, urgency trigger. "
                    "Make it feel like a no-brainer upgrade, not a hard sell."
                ),
                user=(
                    f"Customer just bought: {original_product} (${original_price})\n"
                    f"Upsell offer: {upsell_product} (${upsell_price})\n\n"
                    "Create a high-converting upsell."
                ),
                model=AIModel.CREATIVE,
                max_tokens=300,
            )
            if resp.success:
                lines = [l.strip() for l in resp.content.strip().split("\n") if l.strip()]
                offer.headline = lines[0] if lines else f"Upgrade to {upsell_product} — Save More!"
                offer.reason = resp.content
                offer.urgency_trigger = "Limited time offer — add before checkout closes!"
        except Exception:
            pass

        if not offer.headline:
            offer.headline = f"Complete Your Order — Add {upsell_product} for ${upsell_price:.2f}!"
        if not offer.reason:
            offer.reason = f"Customers who bought {original_product} also love {upsell_product}."
        if not offer.urgency_trigger:
            offer.urgency_trigger = "Add now — this offer disappears after checkout."

        offer.acceptance_rate_pct = round(15.0 + (original_price / upsell_price) * 10, 1)
        offer.acceptance_rate_pct = min(offer.acceptance_rate_pct, 35.0)

        self._upsells.append(offer.to_dict())
        await self._save()
        return offer

    async def create_abandoned_cart_sequence(
        self, product_name: str, price: float, discount_pct: float = 10.0
    ) -> ShopifyFunnel:
        """AI generates 3-email abandoned cart recovery sequence."""
        await self._load()
        funnel = ShopifyFunnel(
            funnel_type="abandoned_cart",
            product_name=product_name,
            discount_pct=discount_pct,
        )

        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system=(
                    "You are a Shopify email marketing expert. Create a 3-email abandoned cart sequence. "
                    "Email 1 (1hr): Friendly reminder, no discount. "
                    "Email 2 (24hr): Social proof + urgency. "
                    "Email 3 (48hr): Final offer with discount code. "
                    "Each email needs: subject line, opening hook, body, CTA."
                ),
                user=(
                    f"Product: {product_name} (${price:.2f})\n"
                    f"Discount available: {discount_pct}% off\n\n"
                    "Write the 3-email abandoned cart sequence."
                ),
                model=AIModel.CREATIVE,
                max_tokens=800,
            )
            if resp.success:
                funnel.body_copy = resp.content
        except Exception:
            pass

        funnel.stages = [
            {
                "email": 1,
                "delay": "1 hour",
                "subject": f"You left something behind — {product_name}",
                "hook": "Your cart is getting lonely...",
                "cta": "Complete Your Order",
                "discount": False,
            },
            {
                "email": 2,
                "delay": "24 hours",
                "subject": f"Others are buying {product_name} right now",
                "hook": "Don't miss out — stock is limited.",
                "cta": "Grab Yours Before It's Gone",
                "discount": False,
            },
            {
                "email": 3,
                "delay": "48 hours",
                "subject": f"Last chance — {int(discount_pct)}% off your {product_name}",
                "hook": f"Here's {int(discount_pct)}% off. Just for you.",
                "cta": f"Claim {int(discount_pct)}% Off Now",
                "discount": True,
                "discount_pct": discount_pct,
            },
        ]
        funnel.headline = f"Recover lost {product_name} sales automatically"
        funnel.cta = "Complete your purchase"
        funnel.expected_cvr_pct = round(5.0 + discount_pct * 0.3, 1)
        funnel.expected_aov_lift_pct = 0.0

        self._funnels.append(funnel.to_dict())
        await self._save()
        return funnel

    async def create_landing_page(
        self,
        product_name: str,
        offer: str,
        target_audience: str,
        price: float = 0.0,
    ) -> ShopifyFunnel:
        """AI generates high-converting landing page copy."""
        await self._load()
        funnel = ShopifyFunnel(funnel_type="landing", product_name=product_name)

        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system=(
                    "You are a direct-response copywriter. Write a high-converting landing page. "
                    "Structure: Headline (benefit + curiosity), Subheadline (specificity), "
                    "3 bullet points (features → benefits), Social proof hook, CTA button text. "
                    "Use power words, urgency, and specificity."
                ),
                user=(
                    f"Product: {product_name}\nOffer: {offer}\n"
                    f"Target audience: {target_audience}\n"
                    f"Price: ${price:.2f}\n\n"
                    "Write the landing page copy."
                ),
                model=AIModel.CREATIVE,
                max_tokens=600,
            )
            if resp.success:
                lines = [l.strip() for l in resp.content.strip().split("\n") if l.strip()]
                funnel.headline = lines[0] if lines else f"Get {product_name} — {offer}"
                funnel.body_copy = resp.content
        except Exception:
            pass

        if not funnel.headline:
            funnel.headline = f"Get {product_name} — {offer}"
        if not funnel.body_copy:
            funnel.body_copy = (
                f"Finally — a {product_name} built for {target_audience}. "
                f"Stop struggling. Start winning. {offer}."
            )

        funnel.stages = [
            {"stage": "hero", "element": "headline", "content": funnel.headline},
            {
                "stage": "benefits",
                "element": "bullets",
                "content": ["Save time", "Increase results", "Zero risk"],
            },
            {
                "stage": "social_proof",
                "element": "testimonial",
                "content": "Join 1,000+ happy customers",
            },
            {"stage": "cta", "element": "button", "content": f"Get {product_name} Now"},
        ]
        funnel.cta = f"Get {product_name} Now"
        funnel.expected_cvr_pct = 3.5
        funnel.expected_aov_lift_pct = 0.0

        self._funnels.append(funnel.to_dict())
        await self._save()
        return funnel

    async def optimize_checkout(self, product_name: str, pain_points: list) -> dict:
        """AI identifies checkout friction points and generates fixes."""
        ai = get_ai_client()
        content = ""
        try:
            pain_str = ", ".join(pain_points) if pain_points else "none specified"
            resp = await ai.complete(
                system=(
                    "You are a Shopify checkout optimization expert. "
                    "Identify friction points and provide specific copy/UX fixes to increase checkout completion rate."
                ),
                user=f"Product: {product_name}\nPain points: {pain_str}\n\nOptimize the checkout experience.",
                model=AIModel.STRATEGY,
                max_tokens=400,
            )
            content = resp.content if resp.success else ""
        except Exception:
            pass

        return {
            "product": product_name,
            "friction_points": pain_points
            or ["too many steps", "no trust signals", "unclear shipping"],
            "fixes": [
                "Add trust badges near payment fields",
                "Show shipping cost upfront (no surprise at checkout)",
                "Add progress indicator (Step 2 of 3)",
                "Enable one-click buy for returning customers",
                "Add money-back guarantee copy near CTA",
            ],
            "expected_cvr_lift_pct": 12.5,
            "analysis": content,
        }

    async def create_post_purchase_flow(self, product_name: str, category: str) -> ShopifyFunnel:
        """AI generates post-purchase upsell + review request sequence."""
        await self._load()
        funnel = ShopifyFunnel(funnel_type="post_purchase", product_name=product_name)

        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system="You are a Shopify retention expert. Create a post-purchase email sequence to maximize LTV.",
                user=f"Product: {product_name}, Category: {category}. Create 3-email post-purchase sequence: thank you + upsell, review request, referral offer.",
                model=AIModel.CREATIVE,
                max_tokens=500,
            )
            if resp.success:
                funnel.body_copy = resp.content
        except Exception:
            pass

        funnel.stages = [
            {
                "email": 1,
                "delay": "immediately",
                "type": "thank_you",
                "subject": f"Your {product_name} is on its way!",
                "includes_upsell": True,
            },
            {
                "email": 2,
                "delay": "5 days",
                "type": "review_request",
                "subject": f"How's your {product_name}?",
                "includes_upsell": False,
            },
            {
                "email": 3,
                "delay": "14 days",
                "type": "referral",
                "subject": "Share the love — get rewarded",
                "includes_upsell": False,
            },
        ]
        funnel.headline = f"Turn every {product_name} buyer into a loyal customer"
        funnel.cta = "Share with a friend"
        funnel.expected_cvr_pct = 0.0
        funnel.expected_aov_lift_pct = 18.0

        self._funnels.append(funnel.to_dict())
        await self._save()
        return funnel

    def funnel_stats(self) -> dict:
        by_type: dict = {}
        for f in self._funnels:
            ft = f.get("funnel_type", "unknown")
            by_type[ft] = by_type.get(ft, 0) + 1
        return {
            "total_funnels": len(self._funnels),
            "total_upsells": len(self._upsells),
            "by_type": by_type,
            "avg_expected_cvr_pct": round(
                sum(f.get("expected_cvr_pct", 0.0) for f in self._funnels)
                / max(len(self._funnels), 1),
                1,
            ),
        }

    def recent_funnels(self, limit: int = 10) -> list[dict]:
        return sorted(self._funnels, key=lambda x: x.get("created_at", 0), reverse=True)[:limit]


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: ShopifyFunnelEngine | None = None


def get_shopify_funnel_engine() -> ShopifyFunnelEngine:
    global _instance
    if _instance is None:
        _instance = ShopifyFunnelEngine()
    return _instance
