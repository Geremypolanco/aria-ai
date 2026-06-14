"""
Business opportunity synthesis.
Combines trend, demand, and competition signals into actionable opportunities ranked by ROI.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.market.opportunities")

_CACHE_KEY = "market:opportunities:v1"
_CACHE_TTL = 86400 * 30  # 30 days

# ── Opportunity templates per type ─────────────────────────────────────────────

_OPPORTUNITY_TEMPLATES: dict[str, list[dict]] = {
    "content": [
        {
            "title_tpl": "{niche} YouTube Channel",
            "description_tpl": "Build a YouTube channel focused on {niche} education and tutorials.",
            "ease": 65.0,
            "rev_min": 200, "rev_max": 3000,
            "ttfr": 45,
            "actions": [
                "Research top 10 {niche} videos",
                "Create channel and upload first 5 videos",
                "Optimize titles and thumbnails",
                "Publish 2 videos/week consistently",
                "Enable monetization at 1,000 subs",
            ],
        },
        {
            "title_tpl": "{niche} Newsletter",
            "description_tpl": "Curate weekly {niche} insights and monetize through sponsorships.",
            "ease": 80.0,
            "rev_min": 100, "rev_max": 2000,
            "ttfr": 30,
            "actions": [
                "Set up newsletter on Beehiiv or Substack",
                "Write 4 pilot issues",
                "Promote in {niche} communities",
                "Reach 500 subscribers before pitching sponsors",
            ],
        },
    ],
    "product": [
        {
            "title_tpl": "{niche} Digital Template Pack",
            "description_tpl": "Create and sell premium templates for {niche} practitioners.",
            "ease": 70.0,
            "rev_min": 150, "rev_max": 2500,
            "ttfr": 14,
            "actions": [
                "Identify top 5 recurring needs in {niche}",
                "Design 10 templates in Canva or Notion",
                "Set up Gumroad or Lemon Squeezy store",
                "Launch with $50 promotional budget",
            ],
        },
    ],
    "service": [
        {
            "title_tpl": "{niche} Consulting Package",
            "description_tpl": "Offer 1-on-1 consulting for {niche} businesses and creators.",
            "ease": 55.0,
            "rev_min": 500, "rev_max": 5000,
            "ttfr": 7,
            "actions": [
                "Define 3 consulting tiers ($99/$299/$999)",
                "Create landing page on Carrd or Notion",
                "Outreach to 50 prospects on LinkedIn",
                "Deliver first paid session",
            ],
        },
    ],
    "affiliate": [
        {
            "title_tpl": "{niche} Affiliate Review Site",
            "description_tpl": "Build SEO-optimized review content for top {niche} products.",
            "ease": 60.0,
            "rev_min": 50, "rev_max": 2000,
            "ttfr": 60,
            "actions": [
                "Choose 5 high-commission {niche} affiliate programs",
                "Create 20 long-form review articles",
                "Optimize for low-competition keywords",
                "Build backlinks via guest posting",
            ],
        },
    ],
}


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class BusinessOpportunity:
    opp_id: str
    title: str
    description: str
    niche: str
    opportunity_type: str  # content | product | service | affiliate
    demand_score: float
    competition_score: float
    ease_score: float
    total_score: float
    estimated_monthly_revenue_usd: float
    time_to_first_revenue_days: int
    action_items: list[str]
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "opp_id": self.opp_id,
            "title": self.title,
            "description": self.description,
            "niche": self.niche,
            "opportunity_type": self.opportunity_type,
            "demand_score": self.demand_score,
            "competition_score": self.competition_score,
            "ease_score": self.ease_score,
            "total_score": self.total_score,
            "estimated_monthly_revenue_usd": self.estimated_monthly_revenue_usd,
            "time_to_first_revenue_days": self.time_to_first_revenue_days,
            "action_items": self.action_items,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BusinessOpportunity:
        return cls(
            opp_id=data["opp_id"],
            title=data["title"],
            description=data["description"],
            niche=data["niche"],
            opportunity_type=data["opportunity_type"],
            demand_score=data["demand_score"],
            competition_score=data["competition_score"],
            ease_score=data["ease_score"],
            total_score=data["total_score"],
            estimated_monthly_revenue_usd=data["estimated_monthly_revenue_usd"],
            time_to_first_revenue_days=data["time_to_first_revenue_days"],
            action_items=data.get("action_items", []),
            created_at=data.get("created_at", time.time()),
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _compute_total_score(demand: float, competition: float, ease: float) -> float:
    """Weighted aggregate: demand 40%, ease 35%, low-competition bonus 25%."""
    competition_inv = 100.0 - competition
    return round((demand * 0.40 + ease * 0.35 + competition_inv * 0.25), 2)


def _build_from_template(
    tpl: dict,
    niche: str,
    opp_type: str,
    seed: int,
    budget_usd: float,
) -> BusinessOpportunity:
    noise = (seed % 30) - 15  # -15 to +14
    demand = min(100.0, max(10.0, 55.0 + noise))
    competition = min(100.0, max(5.0, 40.0 + (seed % 20) - 10))
    ease = tpl["ease"] + ((seed % 10) - 5)
    rev = tpl["rev_min"] + (seed % (tpl["rev_max"] - tpl["rev_min"]))
    # Scale revenue by budget
    rev_scaled = rev * min(3.0, max(0.5, budget_usd / 1000.0))

    return BusinessOpportunity(
        opp_id=str(uuid.uuid4()),
        title=tpl["title_tpl"].format(niche=niche.title()),
        description=tpl["description_tpl"].format(niche=niche),
        niche=niche,
        opportunity_type=opp_type,
        demand_score=round(demand, 2),
        competition_score=round(competition, 2),
        ease_score=round(ease, 2),
        total_score=_compute_total_score(demand, competition, ease),
        estimated_monthly_revenue_usd=round(rev_scaled, 2),
        time_to_first_revenue_days=tpl["ttfr"],
        action_items=[a.format(niche=niche) for a in tpl["actions"]],
    )


# ── Main class ─────────────────────────────────────────────────────────────────

class OpportunityFinder:
    """Synthesizes market signals into ranked business opportunities."""

    def __init__(self) -> None:
        self._opportunities: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._opportunities = data
        except Exception as exc:
            logger.warning("OpportunityFinder._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._opportunities, ttl_seconds=_CACHE_TTL)
        except Exception as exc:
            logger.warning("OpportunityFinder._save failed: %s", exc)

    async def find_opportunities(
        self,
        niche: str,
        budget_usd: float = 1000.0,
    ) -> list[BusinessOpportunity]:
        """Generate 3-5 ranked business opportunities for a niche."""
        await self._load()
        seed = sum(ord(c) for c in niche)
        opportunities: list[BusinessOpportunity] = []

        # Try AI for enriched opportunities first
        try:
            ai = get_ai_client()
            if ai:
                prompt = (
                    f"Generate 4 business opportunities for the '{niche}' niche with a ${budget_usd:.0f} budget. "
                    "For each include: title, description, opportunity_type (content/product/service/affiliate), "
                    "demand_score (0-100), competition_score (0-100), ease_score (0-100), "
                    "estimated_monthly_revenue_usd, time_to_first_revenue_days, action_items (list of 4). "
                    "Return JSON: {\"opportunities\": [...]}"
                )
                result = await ai.generate(prompt, model=AIModel.FAST, json_mode=True)
                if result and isinstance(result, dict):
                    ai_opps = result.get("opportunities", [])
                    for opp_data in ai_opps[:5]:
                        demand = float(opp_data.get("demand_score", 60))
                        competition = float(opp_data.get("competition_score", 40))
                        ease = float(opp_data.get("ease_score", 60))
                        opp = BusinessOpportunity(
                            opp_id=str(uuid.uuid4()),
                            title=str(opp_data.get("title", f"{niche.title()} Opportunity")),
                            description=str(opp_data.get("description", "")),
                            niche=niche,
                            opportunity_type=str(opp_data.get("opportunity_type", "content")),
                            demand_score=round(demand, 2),
                            competition_score=round(competition, 2),
                            ease_score=round(ease, 2),
                            total_score=_compute_total_score(demand, competition, ease),
                            estimated_monthly_revenue_usd=float(
                                opp_data.get("estimated_monthly_revenue_usd", 500)
                            ),
                            time_to_first_revenue_days=int(
                                opp_data.get("time_to_first_revenue_days", 30)
                            ),
                            action_items=list(opp_data.get("action_items", [])),
                        )
                        opportunities.append(opp)
                    if opportunities:
                        opportunities.sort(key=lambda o: o.total_score, reverse=True)
                        for opp in opportunities:
                            self._opportunities.append(opp.to_dict())
                        await self._save()
                        return opportunities
        except Exception as exc:
            logger.debug("find_opportunities AI call failed: %s", exc)

        # Fallback: use templates
        opp_types = list(_OPPORTUNITY_TEMPLATES.keys())
        for i, opp_type in enumerate(opp_types):
            templates = _OPPORTUNITY_TEMPLATES[opp_type]
            tpl = templates[(seed + i) % len(templates)]
            opp = _build_from_template(tpl, niche, opp_type, seed + i * 17, budget_usd)
            opportunities.append(opp)

        # Ensure at least 3 and at most 5
        opportunities = opportunities[:5]
        opportunities.sort(key=lambda o: o.total_score, reverse=True)

        for opp in opportunities:
            self._opportunities.append(opp.to_dict())
        await self._save()
        return opportunities

    async def rank_by_roi(
        self,
        opportunities: list[BusinessOpportunity],
    ) -> list[BusinessOpportunity]:
        """Sort opportunities by monthly revenue / time-to-revenue (ROI velocity)."""
        return sorted(
            opportunities,
            key=lambda o: o.estimated_monthly_revenue_usd / max(o.time_to_first_revenue_days, 1),
            reverse=True,
        )

    async def quick_wins(self, niche: str) -> list[BusinessOpportunity]:
        """Return opportunities achievable within 14 days."""
        await self._load()
        niche_opps = [
            BusinessOpportunity.from_dict(o)
            for o in self._opportunities
            if o.get("niche") == niche and o.get("time_to_first_revenue_days", 999) <= 14
        ]
        niche_opps.sort(key=lambda o: o.total_score, reverse=True)
        return niche_opps

    def summary(self) -> dict:
        total = len(self._opportunities)
        avg_score = (
            sum(o.get("total_score", 0) for o in self._opportunities) / total
            if total else 0.0
        )
        return {
            "total_opportunities": total,
            "avg_total_score": round(avg_score, 2),
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_opportunity_finder_instance: Optional[OpportunityFinder] = None


def get_opportunity_finder() -> OpportunityFinder:
    global _opportunity_finder_instance
    if _opportunity_finder_instance is None:
        _opportunity_finder_instance = OpportunityFinder()
    return _opportunity_finder_instance
