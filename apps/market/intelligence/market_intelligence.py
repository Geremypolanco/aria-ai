"""
MarketIntelligence — Aggregated market signals for strategic positioning.
Consolidates trend, competition, and demand data into actionable snapshots.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_KEY = "market:intelligence:v1"
_TTL = 86400 * 7


@dataclass
class MarketSnapshot:
    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    niche: str = ""
    trend_score: float = 0.5
    competition_level: str = "medium"
    demand_momentum: str = "stable"
    opportunity_count: int = 0
    top_opportunity: str = ""
    pricing_pressure: str = "moderate"
    market_maturity: str = "growing"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "niche": self.niche,
            "trend_score": self.trend_score,
            "competition_level": self.competition_level,
            "demand_momentum": self.demand_momentum,
            "opportunity_count": self.opportunity_count,
            "top_opportunity": self.top_opportunity,
            "pricing_pressure": self.pricing_pressure,
            "market_maturity": self.market_maturity,
            "created_at": self.created_at,
        }


class MarketIntelligence:
    def __init__(self) -> None:
        self._snapshots: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, list):
                    self._snapshots = data
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, self._snapshots[-200:], ttl_seconds=_TTL)
        except Exception:
            pass

    async def analyze_market(self, niche: str) -> MarketSnapshot:
        await self._load()
        trend_score = 0.5
        competition_level = "medium"
        demand_momentum = "stable"
        opportunity_count = 3

        try:
            from apps.market.trends.trend_analyzer import get_trend_analyzer

            report = await get_trend_analyzer().analyze_niche(niche)
            trend_score = getattr(report, "trend_score", 0.5)
        except Exception:
            # Heuristic defaults by niche type
            if any(w in niche.lower() for w in ["ai", "crypto", "saas"]):
                trend_score = 0.82
                demand_momentum = "rising"
            elif any(w in niche.lower() for w in ["food", "local", "retail"]):
                trend_score = 0.45

        try:
            from apps.market.competition.competitor_monitor import get_competitor_monitor

            landscape = await get_competitor_monitor().competitive_landscape(niche)
            comp = landscape.get("competition_intensity", 0.5)
            competition_level = "high" if comp > 0.65 else "low" if comp < 0.35 else "medium"
        except Exception:
            pass

        try:
            from apps.market.opportunities.opportunity_finder import get_opportunity_finder

            opps = await get_opportunity_finder().find_opportunities(niche, 1000.0)
            opportunity_count = len(opps)
            if opps:
                top_opportunity = opps[0].title if hasattr(opps[0], "title") else str(opps[0])
            else:
                top_opportunity = f"SEO content for {niche}"
        except Exception:
            top_opportunity = f"Content marketing for {niche}"

        # Classify maturity
        if trend_score > 0.75 and competition_level == "low":
            market_maturity = "emerging"
        elif trend_score > 0.6:
            market_maturity = "growing"
        elif competition_level == "high" and trend_score < 0.4:
            market_maturity = "mature"
        else:
            market_maturity = "growing"

        pricing_pressure = "high" if competition_level == "high" else "moderate"

        snapshot = MarketSnapshot(
            niche=niche,
            trend_score=round(trend_score, 3),
            competition_level=competition_level,
            demand_momentum=demand_momentum,
            opportunity_count=opportunity_count,
            top_opportunity=top_opportunity,
            pricing_pressure=pricing_pressure,
            market_maturity=market_maturity,
        )
        self._snapshots.append(snapshot.to_dict())
        await self._save()
        return snapshot

    async def identify_entry_points(self, niche: str) -> list[dict]:
        return [
            {
                "strategy": "SEO content",
                "channel": "organic",
                "effort": "high",
                "time_to_revenue_days": 90,
                "risk_level": "low",
            },
            {
                "strategy": "Paid ads",
                "channel": "meta/google",
                "effort": "medium",
                "time_to_revenue_days": 14,
                "risk_level": "medium",
            },
            {
                "strategy": "Influencer partnership",
                "channel": "instagram/tiktok",
                "effort": "medium",
                "time_to_revenue_days": 30,
                "risk_level": "medium",
            },
            {
                "strategy": "Quiz funnel",
                "channel": "social",
                "effort": "medium",
                "time_to_revenue_days": 21,
                "risk_level": "low",
            },
            {
                "strategy": "Bundle flash offer",
                "channel": "email/sms",
                "effort": "low",
                "time_to_revenue_days": 7,
                "risk_level": "low",
            },
        ]

    async def competitive_positioning(self, niche: str, strengths: list[str] = None) -> dict:
        if strengths is None:
            strengths = []
        try:
            ai = get_ai_client()
            strengths_text = ", ".join(strengths) if strengths else "AI-powered automation"
            resp = await ai.complete(
                system="You are a brand strategist.",
                user=(
                    f"In 3 sentences, define a unique competitive positioning for a brand in '{niche}' "
                    f"with these strengths: {strengths_text}. Return JSON with keys: "
                    f"position, unique_angle, key_message, target_segment, differentiation"
                ),
                model=AIModel.STRATEGY,
                max_tokens=200,
            )
            if resp.success and resp.content:
                import json
                import re

                match = re.search(r"\{.*\}", resp.content, re.DOTALL)
                if match:
                    return json.loads(match.group())
        except Exception:
            pass
        return {
            "position": f"The AI-native {niche} solution",
            "unique_angle": "Autonomous optimization while you sleep",
            "key_message": f"The only {niche} platform that learns and improves automatically",
            "target_segment": "Growth-focused entrepreneurs",
            "differentiation": "AI-driven personalization at scale",
        }

    def latest_snapshot(self, niche: str) -> dict | None:
        matching = [s for s in self._snapshots if s.get("niche") == niche]
        return matching[-1] if matching else None

    def intelligence_dashboard(self) -> dict:
        if not self._snapshots:
            return {"total_snapshots": 0}
        by_niche = {}
        for s in self._snapshots:
            n = s.get("niche", "")
            if n not in by_niche or s["created_at"] > by_niche[n]["created_at"]:
                by_niche[n] = s
        top_niches = sorted(by_niche.values(), key=lambda x: x.get("trend_score", 0), reverse=True)
        rising = [s["niche"] for s in top_niches if s.get("demand_momentum") == "rising"]
        low_competition = [s["niche"] for s in top_niches if s.get("competition_level") == "low"]
        return {
            "total_snapshots": len(self._snapshots),
            "niches_analyzed": len(by_niche),
            "top_niches_by_trend": [s["niche"] for s in top_niches[:5]],
            "rising_demand_markets": rising[:5],
            "low_competition_opportunities": low_competition[:5],
        }


_instance: MarketIntelligence | None = None


def get_market_intelligence() -> MarketIntelligence:
    global _instance
    if _instance is None:
        _instance = MarketIntelligence()
    return _instance
