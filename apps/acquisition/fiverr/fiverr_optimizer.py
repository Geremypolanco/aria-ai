"""
ARIA AI — Fiverr Optimizer
Phase 11: AI-powered Fiverr gig creation, SEO optimization, and pricing.

Capabilities:
  - Full gig creation with packages and FAQ
  - Title SEO optimization
  - Competitive pricing recommendations
  - Portfolio descriptions
  - Gig analytics
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

# ── Redis configuration ────────────────────────────────────────────────────────
_REDIS_KEY = "acquisition:fiverr:v1"
_TTL_90D = 60 * 60 * 24 * 90


# ══════════════════════════════════════════════════════════════════════════════
# Domain object
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FiverrGig:
    gig_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    category: str = ""
    description: str = ""
    packages: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)
    faq: list = field(default_factory=list)
    seo_score: float = 0.0
    status: str = "draft"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "gig_id": self.gig_id,
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "packages": self.packages,
            "tags": self.tags,
            "faq": self.faq,
            "seo_score": self.seo_score,
            "status": self.status,
            "created_at": self.created_at,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Fiverr Optimizer
# ══════════════════════════════════════════════════════════════════════════════

class FiverrOptimizer:
    """
    AI-powered Fiverr gig optimization system.
    State persisted in Redis (key: acquisition:fiverr:v1, TTL 90d).
    """

    def __init__(self):
        self._gigs: list[dict] = []

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _load(self) -> None:
        cache = get_cache()
        data = await cache.get(_REDIS_KEY)
        if isinstance(data, dict):
            self._gigs = data.get("gigs", [])
        elif isinstance(data, list):
            self._gigs = data

    async def _save(self) -> None:
        cache = get_cache()
        await cache.set(_REDIS_KEY, {"gigs": self._gigs}, ttl_seconds=_TTL_90D)

    def _seo_score(self, title: str, description: str, tags: list) -> float:
        """Score gig SEO based on content richness."""
        title_score = min(len(title.split()) / 10, 0.3)
        desc_score = min(len(description.split()) / 300, 0.5)
        tags_score = min(len(tags) / 5, 0.2)
        return min(title_score + desc_score + tags_score + 0.3, 0.95)

    def _default_packages(self, service_type: str, niche: str) -> dict:
        """Generate default 3-tier packages."""
        return {
            "basic": {
                "name": f"Basic {service_type}",
                "price": 25,
                "delivery_days": 3,
                "features": [f"1 {niche} deliverable", "Basic revisions", "Source files"],
            },
            "standard": {
                "name": f"Standard {service_type}",
                "price": 75,
                "delivery_days": 5,
                "features": [f"3 {niche} deliverables", "Unlimited revisions", "Priority support", "Commercial rights"],
            },
            "premium": {
                "name": f"Premium {service_type}",
                "price": 150,
                "delivery_days": 7,
                "features": [f"5 {niche} deliverables", "Unlimited revisions", "VIP support", "Commercial rights", "Strategy call"],
            },
        }

    # ── Public methods ─────────────────────────────────────────────────────────

    async def create_gig(self, service_type: str, niche: str) -> FiverrGig:
        """AI creates full gig with title, description, 3 packages, tags, FAQ."""
        await self._load()
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a Fiverr gig optimization expert. Create a complete high-converting gig. "
                "Include: SEO-optimized title, compelling 500-word description, 5 relevant tags, "
                "and 5 FAQ pairs that address buyer concerns."
            ),
            user=(
                f"Service type: {service_type}\nNiche: {niche}\n\n"
                "Create complete Fiverr gig content."
            ),
            model=AIModel.CREATIVE,
            max_tokens=800,
        )
        content = resp.content if resp.success else f"Professional {service_type} for {niche}"

        lines = content.strip().split("\n")
        title_line = lines[0] if lines else f"I will provide {service_type} for {niche}"
        # Clean title
        title = title_line.replace("Title:", "").strip()
        if len(title) > 80:
            title = title[:77] + "..."

        packages = self._default_packages(service_type, niche)
        tags = [service_type.lower(), niche.lower(), "professional", "expert", "quality"]

        gig = FiverrGig(
            title=title,
            category=niche,
            description=content,
            packages=packages,
            tags=tags,
            faq=[
                {"q": "How many revisions do you offer?", "a": "Unlimited revisions until you're satisfied."},
                {"q": "What do you need to get started?", "a": f"Just share your {niche} requirements and any examples."},
                {"q": "Do you offer rush delivery?", "a": "Yes! Contact me before ordering for rush options."},
                {"q": "What format will I receive files in?", "a": "All standard formats — ask me for specifics."},
                {"q": "Do I own the commercial rights?", "a": "Yes, full commercial rights included with Standard and Premium."},
            ],
            seo_score=self._seo_score(title, content, tags),
            status="draft",
        )
        self._gigs.append(gig.to_dict())
        await self._save()
        return gig

    async def optimize_gig_title(self, current_title: str, keyword: str) -> str:
        """AI rewrites gig title for Fiverr SEO."""
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a Fiverr SEO expert. Rewrite gig titles for maximum search visibility. "
                "Use: keyword at the start, action verb, benefit, and niche. Keep under 80 chars."
            ),
            user=f"Current title: {current_title}\nKeyword: {keyword}\n\nOptimize the title.",
            model=AIModel.FAST,
            max_tokens=100,
        )
        if not resp.success:
            return f"I will {keyword} professionally and deliver outstanding results"
        optimized = resp.content.strip().split("\n")[0]
        return optimized[:80] if len(optimized) > 80 else optimized

    async def price_packages(
        self, service_type: str, complexity_range: str = "low-high"
    ) -> dict:
        """AI suggests competitive pricing for basic/standard/premium."""
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a Fiverr pricing strategist. Recommend competitive 3-tier pricing "
                "based on service type and market analysis. Consider: competitor pricing, "
                "perceived value, and conversion optimization."
            ),
            user=(
                f"Service: {service_type}\nComplexity range: {complexity_range}\n\n"
                "Recommend pricing for basic, standard, premium packages."
            ),
            model=AIModel.FAST,
            max_tokens=300,
        )
        # Return structured pricing regardless of AI response
        return {
            "basic": {"price": 25, "delivery_days": 3, "reasoning": "Entry-level to attract first orders"},
            "standard": {"price": 75, "delivery_days": 5, "reasoning": "Most popular tier — best value"},
            "premium": {"price": 150, "delivery_days": 7, "reasoning": "High-touch for serious buyers"},
            "ai_analysis": resp.content if resp.success else "",
        }

    async def generate_portfolio_description(self, project: dict) -> str:
        """AI writes portfolio item description."""
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a portfolio copywriter. Write compelling portfolio item descriptions "
                "that showcase results, demonstrate expertise, and build buyer confidence."
            ),
            user=(
                f"Project details: {project}\n\n"
                "Write a compelling portfolio description (2-3 sentences)."
            ),
            model=AIModel.CREATIVE,
            max_tokens=200,
        )
        if resp.success:
            return resp.content.strip()
        return f"Delivered exceptional {project.get('type', 'service')} results for {project.get('client', 'client')} achieving outstanding outcomes."

    def active_gigs(self) -> list[dict]:
        """Return only active gigs."""
        return [g for g in self._gigs if g.get("status") == "active"]

    def gig_analytics(self) -> dict:
        """Return gig analytics."""
        active = sum(1 for g in self._gigs if g.get("status") == "active")
        seo_scores = [g.get("seo_score", 0.0) for g in self._gigs]
        avg_seo = sum(seo_scores) / len(seo_scores) if seo_scores else 0.0
        categories = list({g.get("category", "unknown") for g in self._gigs})
        return {
            "total_gigs": len(self._gigs),
            "active": active,
            "avg_seo_score": round(avg_seo, 3),
            "categories": categories,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: Optional[FiverrOptimizer] = None


def get_fiverr_optimizer() -> FiverrOptimizer:
    global _instance
    if _instance is None:
        _instance = FiverrOptimizer()
    return _instance
