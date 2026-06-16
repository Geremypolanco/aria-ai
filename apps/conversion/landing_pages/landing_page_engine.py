"""
ARIA AI — Landing Page Engine
Phase 13: High-converting landing page generation with A/B variants,
headline optimization, and conversion rate estimation.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_KEY = "conversion:landing_pages:v1"
_TTL = 86400 * 60


@dataclass
class LandingPage:
    page_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    product: str = ""
    offer: str = ""
    target_audience: str = ""
    headline: str = ""
    subheadline: str = ""
    hero_copy: str = ""
    bullet_points: list = field(default_factory=list)
    social_proof: str = ""
    urgency_trigger: str = ""
    cta_primary: str = ""
    cta_secondary: str = ""
    faq: list = field(default_factory=list)
    estimated_cvr_pct: float = 0.0
    ab_variant: str = "A"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "page_id": self.page_id,
            "product": self.product,
            "offer": self.offer,
            "target_audience": self.target_audience,
            "headline": self.headline,
            "subheadline": self.subheadline,
            "hero_copy": self.hero_copy,
            "bullet_points": self.bullet_points,
            "social_proof": self.social_proof,
            "urgency_trigger": self.urgency_trigger,
            "cta_primary": self.cta_primary,
            "cta_secondary": self.cta_secondary,
            "faq": self.faq,
            "estimated_cvr_pct": self.estimated_cvr_pct,
            "ab_variant": self.ab_variant,
            "created_at": self.created_at,
        }


class LandingPageEngine:
    """
    High-converting landing page generator.
    State persisted in Redis (key: conversion:landing_pages:v1, TTL 60d).
    """

    def __init__(self) -> None:
        self._pages: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._pages = data.get("pages", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, {"pages": self._pages[-300:]}, ttl_seconds=_TTL)
        except Exception:
            pass

    async def create_page(
        self,
        product: str,
        offer: str,
        target_audience: str,
        price: float = 0.0,
    ) -> LandingPage:
        """AI generates a complete high-converting landing page."""
        await self._load()
        page = LandingPage(product=product, offer=offer, target_audience=target_audience)

        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system=(
                    "You are a direct-response copywriter. Write a landing page with: "
                    "HEADLINE (benefit + curiosity, ≤10 words), "
                    "SUBHEADLINE (specificity + credibility, ≤20 words), "
                    "HERO COPY (2 sentences, pain → solution), "
                    "BULLETS (5 benefit bullets starting with verbs), "
                    "SOCIAL PROOF (one line with number/result), "
                    "URGENCY (scarcity or deadline trigger), "
                    "CTA (action verb + specific benefit)."
                ),
                user=(
                    f"Product: {product}\nOffer: {offer}\n"
                    f"Target audience: {target_audience}\n"
                    f"Price: ${price:.2f}\n\n"
                    "Write the complete landing page copy."
                ),
                model=AIModel.CREATIVE,
                max_tokens=700,
            )
            if resp.success:
                content = resp.content
                lines = [l.strip() for l in content.split("\n") if l.strip()]
                page.headline = lines[0].replace("HEADLINE:", "").replace("Headline:", "").strip()
                page.subheadline = lines[1].replace("SUBHEADLINE:", "").replace("Subheadline:", "").strip() if len(lines) > 1 else f"The fastest way for {target_audience} to {offer.lower()}"
                page.hero_copy = " ".join(lines[2:4]) if len(lines) > 3 else f"Stop struggling. Start getting results with {product}."
                page.social_proof = "Join 2,000+ customers who've transformed their results"
                page.urgency_trigger = "Limited time: this offer ends at midnight"
                page.cta_primary = f"Get {product} Now"
                page.cta_secondary = "Learn More"
        except Exception:
            pass

        if not page.headline:
            page.headline = f"Get {product} — {offer}"
        if not page.subheadline:
            page.subheadline = f"The proven system for {target_audience} to achieve results fast"
        if not page.hero_copy:
            page.hero_copy = f"Most {target_audience} struggle with {product.lower()}. Not anymore. {offer}."
        if not page.bullet_points:
            page.bullet_points = [
                f"Achieve {offer} faster than ever before",
                "Save hours of manual work every week",
                "Proven system used by thousands of customers",
                "No technical skills required",
                "30-day money-back guarantee",
            ]
        if not page.social_proof:
            page.social_proof = f"Join 2,000+ {target_audience} who already use {product}"
        if not page.urgency_trigger:
            page.urgency_trigger = "Limited time offer — price increases soon"
        if not page.cta_primary:
            page.cta_primary = f"Get {product} Now"
        if not page.cta_secondary:
            page.cta_secondary = "See How It Works"
        if not page.faq:
            page.faq = [
                {"q": "How fast will I see results?", "a": f"Most customers see results within 7 days of using {product}."},
                {"q": "Is there a money-back guarantee?", "a": "Yes — 30-day no-questions-asked refund."},
                {"q": "Who is this for?", "a": f"Designed specifically for {target_audience}."},
            ]

        page.estimated_cvr_pct = 3.5
        if price > 0 and price < 100:
            page.estimated_cvr_pct = 5.5
        elif price > 500:
            page.estimated_cvr_pct = 1.5

        self._pages.append(page.to_dict())
        await self._save()
        return page

    async def generate_headline_variants(self, product: str, audience: str, count: int = 5) -> list[str]:
        """AI generates multiple headline variants for A/B testing."""
        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system="You are a headline copywriter. Generate scroll-stopping headlines using: curiosity, number, benefit, fear, proof.",
                user=f"Product: {product}, Audience: {audience}. Write {count} headline variants (≤10 words each). One per line.",
                model=AIModel.CREATIVE,
                max_tokens=300,
            )
            if resp.success:
                lines = [l.strip() for l in resp.content.strip().split("\n") if l.strip()]
                return lines[:count]
        except Exception:
            pass

        return [
            f"Finally — {product} That Actually Works for {audience}",
            f"The {product} Secret That {audience} Don't Know",
            f"Get {product} Results in 7 Days or Your Money Back",
            f"Why 2,000+ {audience} Choose {product}",
            f"Stop Struggling. {product} Changes Everything.",
        ][:count]

    async def create_ab_variant(self, original_page: LandingPage) -> LandingPage:
        """Generate a B variant with different headline and CTA approach."""
        await self._load()
        variants = await self.generate_headline_variants(
            original_page.product, original_page.target_audience, count=1
        )

        variant = LandingPage(
            product=original_page.product,
            offer=original_page.offer,
            target_audience=original_page.target_audience,
            headline=variants[0] if variants else f"Try {original_page.product} Risk-Free Today",
            subheadline=original_page.subheadline,
            hero_copy=original_page.hero_copy,
            bullet_points=original_page.bullet_points,
            social_proof=original_page.social_proof,
            urgency_trigger="Only 47 spots remaining at this price",
            cta_primary=f"Start Your Free Trial",
            cta_secondary="Watch Demo First",
            faq=original_page.faq,
            estimated_cvr_pct=original_page.estimated_cvr_pct * 1.1,
            ab_variant="B",
        )

        self._pages.append(variant.to_dict())
        await self._save()
        return variant

    def page_stats(self) -> dict:
        by_variant: dict = {}
        for p in self._pages:
            v = p.get("ab_variant", "A")
            by_variant[v] = by_variant.get(v, 0) + 1
        avg_cvr = sum(p.get("estimated_cvr_pct", 0.0) for p in self._pages) / max(len(self._pages), 1)
        return {
            "total_pages": len(self._pages),
            "by_variant": by_variant,
            "avg_estimated_cvr_pct": round(avg_cvr, 2),
        }

    def recent_pages(self, limit: int = 10) -> list[dict]:
        return sorted(self._pages, key=lambda x: x.get("created_at", 0), reverse=True)[:limit]


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: Optional[LandingPageEngine] = None


def get_landing_page_engine() -> LandingPageEngine:
    global _instance
    if _instance is None:
        _instance = LandingPageEngine()
    return _instance
