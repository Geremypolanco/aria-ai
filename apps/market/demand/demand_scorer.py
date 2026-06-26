"""
Market demand scoring and opportunity detection.
Scores keywords by demand/supply ratio to surface high-opportunity gaps.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.market.demand")

_CACHE_KEY = "market:demand:v1"
_CACHE_TTL = 86400 * 7  # 7 days

# Words that indicate commercial intent / high demand
_COMMERCIAL_WORDS = {
    "buy",
    "best",
    "review",
    "reviews",
    "top",
    "how to",
    "guide",
    "cheap",
    "price",
    "discount",
    "deal",
    "vs",
    "compare",
    "comparison",
    "recommended",
    "tutorial",
    "learn",
    "free",
    "affordable",
}

# Niches considered saturated (high supply)
_HIGH_SUPPLY_NICHES = {
    "fitness",
    "weight loss",
    "make money online",
    "crypto",
    "dating",
    "personal finance",
    "diet",
    "tech reviews",
    "gaming",
}


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class DemandScore:
    keyword: str
    niche: str
    demand_score: float  # 0-100
    supply_score: float  # 0-100
    opportunity_score: float  # 0-100 (demand - supply, capped)
    search_volume_est: int
    competition_level: str  # low | medium | high
    monetization_potential: str  # low | medium | high
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "keyword": self.keyword,
            "niche": self.niche,
            "demand_score": self.demand_score,
            "supply_score": self.supply_score,
            "opportunity_score": self.opportunity_score,
            "search_volume_est": self.search_volume_est,
            "competition_level": self.competition_level,
            "monetization_potential": self.monetization_potential,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DemandScore:
        return cls(
            keyword=data["keyword"],
            niche=data["niche"],
            demand_score=data["demand_score"],
            supply_score=data["supply_score"],
            opportunity_score=data["opportunity_score"],
            search_volume_est=data.get("search_volume_est", 0),
            competition_level=data.get("competition_level", "medium"),
            monetization_potential=data.get("monetization_potential", "medium"),
            timestamp=data.get("timestamp", time.time()),
        )


# ── Heuristic scoring logic ────────────────────────────────────────────────────


def _heuristic_demand(keyword: str) -> float:
    """Estimate demand 0-100 using keyword length and commercial intent signals."""
    kw_lower = keyword.lower()
    # Shorter keywords = broader demand
    length_score = max(0, 80 - len(keyword) * 3)

    # Commercial word bonus
    commercial_bonus = 0
    for word in _COMMERCIAL_WORDS:
        if word in kw_lower:
            commercial_bonus += 15
            break

    # Question words = informational intent, still valuable
    if any(kw_lower.startswith(q) for q in ("how", "what", "why", "when", "where", "which")):
        commercial_bonus += 10

    return min(100.0, length_score + commercial_bonus)


def _heuristic_supply(keyword: str, niche: str) -> float:
    """Estimate supply/competition 0-100."""
    niche_lower = niche.lower()
    base_supply = 60.0 if niche_lower in _HIGH_SUPPLY_NICHES else 35.0

    # Longer, more specific keywords tend to have lower supply
    specificity_discount = min(30, len(keyword) * 1.5)

    seed = sum(ord(c) for c in keyword) % 20
    noise = seed - 10  # -10 to +9

    return max(5.0, min(95.0, base_supply - specificity_discount + noise))


def _monetization_level(demand: float, supply: float) -> str:
    opp = demand - supply
    if opp > 30 or demand > 70:
        return "high"
    if opp > 10 or demand > 50:
        return "medium"
    return "low"


def _competition_level(supply: float) -> str:
    if supply > 65:
        return "high"
    if supply > 35:
        return "medium"
    return "low"


# ── Main class ─────────────────────────────────────────────────────────────────


class DemandScorer:
    """Scores keywords by demand/supply ratio to surface opportunities."""

    def __init__(self) -> None:
        self._scores: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._scores = data
        except Exception as exc:
            logger.warning("DemandScorer._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._scores, ttl_seconds=_CACHE_TTL)
        except Exception as exc:
            logger.warning("DemandScorer._save failed: %s", exc)

    async def score_keyword(self, keyword: str, niche: str = "") -> DemandScore:
        """Score a single keyword by demand and supply heuristics, with AI enrichment."""
        await self._load()

        demand = _heuristic_demand(keyword)
        supply = _heuristic_supply(keyword, niche)
        opportunity = max(0.0, min(100.0, demand - supply))

        seed = sum(ord(c) for c in keyword)
        search_volume_est = ((seed % 90) + 10) * 500  # 5,000 – 50,000

        # Try AI enrichment
        try:
            ai = get_ai_client()
            if ai:
                prompt = (
                    f"Score this keyword for market opportunity: '{keyword}' in niche '{niche or 'general'}'. "
                    'Return JSON: {"demand_score": 75, "supply_score": 40, "search_volume_est": 12000}'
                )
                result = await ai.generate(prompt, model=AIModel.FAST, json_mode=True)
                if result and isinstance(result, dict):
                    ai_demand = float(result.get("demand_score", demand))
                    ai_supply = float(result.get("supply_score", supply))
                    demand = min(100.0, max(0.0, ai_demand))
                    supply = min(100.0, max(0.0, ai_supply))
                    opportunity = max(0.0, min(100.0, demand - supply))
                    search_volume_est = int(result.get("search_volume_est", search_volume_est))
        except Exception as exc:
            logger.debug("score_keyword AI call failed: %s", exc)

        score = DemandScore(
            keyword=keyword,
            niche=niche,
            demand_score=round(demand, 2),
            supply_score=round(supply, 2),
            opportunity_score=round(opportunity, 2),
            search_volume_est=search_volume_est,
            competition_level=_competition_level(supply),
            monetization_potential=_monetization_level(demand, supply),
        )
        self._scores.append(score.to_dict())
        await self._save()
        return score

    async def score_batch(self, keywords: list[str], niche: str = "") -> list[DemandScore]:
        """Score multiple keywords and sort by opportunity_score descending."""
        results: list[DemandScore] = []
        for kw in keywords:
            ds = await self.score_keyword(kw, niche)
            results.append(ds)
        results.sort(key=lambda x: x.opportunity_score, reverse=True)
        return results

    async def top_opportunities(self, niche: str, limit: int = 10) -> list[DemandScore]:
        """Return top-scored keywords for a niche sorted by opportunity_score."""
        await self._load()
        niche_scores = [DemandScore.from_dict(s) for s in self._scores if s.get("niche") == niche]
        niche_scores.sort(key=lambda x: x.opportunity_score, reverse=True)
        return niche_scores[:limit]

    async def detect_underserved(self, niche: str) -> list[str]:
        """Return keywords with high demand but low supply (opportunity_score > 60)."""
        await self._load()
        underserved = [
            DemandScore.from_dict(s)
            for s in self._scores
            if s.get("niche") == niche and s.get("opportunity_score", 0) > 60
        ]
        underserved.sort(key=lambda x: x.opportunity_score, reverse=True)
        return [ds.keyword for ds in underserved]

    def summary(self) -> dict:
        total = len(self._scores)
        avg_opp = sum(s.get("opportunity_score", 0) for s in self._scores) / total if total else 0.0
        top_kw = ""
        if self._scores:
            best = max(self._scores, key=lambda s: s.get("opportunity_score", 0))
            top_kw = best.get("keyword", "")
        return {
            "total_scored": total,
            "avg_opportunity_score": round(avg_opp, 2),
            "top_keyword": top_kw,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_demand_scorer_instance: DemandScorer | None = None


def get_demand_scorer() -> DemandScorer:
    global _demand_scorer_instance
    if _demand_scorer_instance is None:
        _demand_scorer_instance = DemandScorer()
    return _demand_scorer_instance
