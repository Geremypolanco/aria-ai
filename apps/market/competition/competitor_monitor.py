"""
Competitor analysis and monitoring.
Tracks competitor profiles, identifies market gaps, and surfaces competitive insights.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.market.competition")

_CACHE_KEY = "market:competitors:v1"
_CACHE_TTL = 86400 * 14  # 14 days


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class CompetitorProfile:
    competitor_id: str
    name: str
    domain: str
    niche: str
    estimated_traffic: int = 0
    content_frequency: str = "unknown"
    pricing_tier: str = "unknown"
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "competitor_id": self.competitor_id,
            "name": self.name,
            "domain": self.domain,
            "niche": self.niche,
            "estimated_traffic": self.estimated_traffic,
            "content_frequency": self.content_frequency,
            "pricing_tier": self.pricing_tier,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CompetitorProfile:
        return cls(
            competitor_id=data["competitor_id"],
            name=data["name"],
            domain=data["domain"],
            niche=data["niche"],
            estimated_traffic=data.get("estimated_traffic", 0),
            content_frequency=data.get("content_frequency", "unknown"),
            pricing_tier=data.get("pricing_tier", "unknown"),
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class CompetitiveInsight:
    insight_id: str
    type: str  # gap | threat | opportunity
    description: str
    priority: int  # 1-5
    competitor_id: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "insight_id": self.insight_id,
            "type": self.type,
            "description": self.description,
            "priority": self.priority,
            "competitor_id": self.competitor_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CompetitiveInsight:
        return cls(
            insight_id=data["insight_id"],
            type=data["type"],
            description=data["description"],
            priority=data.get("priority", 3),
            competitor_id=data["competitor_id"],
            created_at=data.get("created_at", time.time()),
        )


# ── Default fallback data ──────────────────────────────────────────────────────

def _fallback_strengths(name: str, niche: str) -> list[str]:
    seed = sum(ord(c) for c in name + niche)
    options = [
        f"Established brand authority in {niche}",
        "High domain rating and SEO presence",
        "Large engaged community",
        "Consistent content publishing cadence",
        "Strong email list",
        "Paid advertising budget",
        "Multiple monetization streams",
    ]
    indices = [(seed + i * 13) % len(options) for i in range(3)]
    return [options[i] for i in indices]


def _fallback_weaknesses(name: str, niche: str) -> list[str]:
    seed = sum(ord(c) for c in name + niche) + 1
    options = [
        "Limited mobile-first content",
        "Weak short-form video presence",
        "Poor community engagement",
        "Outdated content design",
        "No multilingual support",
        "Slow page load times",
        "Sparse social proof",
    ]
    indices = [(seed + i * 7) % len(options) for i in range(3)]
    return [options[i] for i in indices]


# ── Main class ─────────────────────────────────────────────────────────────────

class CompetitorMonitor:
    """Tracks and analyzes competitors in a given market niche."""

    def __init__(self) -> None:
        self._profiles: dict[str, dict] = {}
        self._insights: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, dict):
                self._profiles = data.get("profiles", {})
                self._insights = data.get("insights", [])
        except Exception as exc:
            logger.warning("CompetitorMonitor._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        data = {
            "profiles": self._profiles,
            "insights": self._insights,
        }
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, data, ttl_seconds=_CACHE_TTL)
        except Exception as exc:
            logger.warning("CompetitorMonitor._save failed: %s", exc)

    async def add_competitor(
        self,
        name: str,
        domain: str,
        niche: str,
    ) -> CompetitorProfile:
        """Create and persist a new competitor profile."""
        await self._load()
        competitor_id = str(uuid.uuid4())
        seed = sum(ord(c) for c in domain)
        profile = CompetitorProfile(
            competitor_id=competitor_id,
            name=name,
            domain=domain,
            niche=niche,
            estimated_traffic=((seed % 90) + 10) * 1000,
            content_frequency="weekly" if seed % 3 == 0 else ("daily" if seed % 3 == 1 else "monthly"),
            pricing_tier="freemium" if seed % 3 == 0 else ("premium" if seed % 3 == 1 else "free"),
            strengths=_fallback_strengths(name, niche),
            weaknesses=_fallback_weaknesses(name, niche),
        )
        self._profiles[competitor_id] = profile.to_dict()
        await self._save()
        return profile

    async def analyze_competitor(self, competitor_id: str) -> CompetitiveInsight:
        """Deep-analyze a competitor and produce insights."""
        await self._load()
        profile_data = self._profiles.get(competitor_id)
        if not profile_data:
            # Return a generic insight if profile not found
            return CompetitiveInsight(
                insight_id=str(uuid.uuid4()),
                type="opportunity",
                description="Competitor profile not found — consider adding it first.",
                priority=2,
                competitor_id=competitor_id,
            )

        profile = CompetitorProfile.from_dict(profile_data)

        # Try AI enrichment
        try:
            ai = get_ai_client()
            if ai:
                prompt = (
                    f"Analyze competitor '{profile.name}' (domain: {profile.domain}) in the '{profile.niche}' niche. "
                    "Identify the biggest threat they pose. "
                    "Return JSON: {\"type\": \"threat\", \"description\": \"...\", \"priority\": 3}"
                )
                result = await ai.generate(prompt, model=AIModel.FAST, json_mode=True)
                if result and isinstance(result, dict):
                    insight = CompetitiveInsight(
                        insight_id=str(uuid.uuid4()),
                        type=result.get("type", "threat"),
                        description=str(result.get("description", "")),
                        priority=max(1, min(5, int(result.get("priority", 3)))),
                        competitor_id=competitor_id,
                    )
                    self._insights.append(insight.to_dict())
                    await self._save()
                    return insight
        except Exception as exc:
            logger.debug("analyze_competitor AI call failed: %s", exc)

        # Fallback deterministic insight
        seed = sum(ord(c) for c in profile.name)
        insight = CompetitiveInsight(
            insight_id=str(uuid.uuid4()),
            type="threat",
            description=(
                f"{profile.name} poses a competitive threat in {profile.niche} "
                f"with estimated {profile.estimated_traffic:,} monthly visitors "
                f"and {profile.content_frequency} content cadence."
            ),
            priority=min(5, max(1, seed % 5 + 1)),
            competitor_id=competitor_id,
        )
        self._insights.append(insight.to_dict())
        await self._save()
        return insight

    async def find_gaps(self, niche: str) -> list[CompetitiveInsight]:
        """Identify market gaps not covered by competitors."""
        await self._load()

        gap_templates = [
            f"No competitor covers beginner-friendly {niche} content",
            f"Short-form video content for {niche} is underserved",
            f"Community-based {niche} platform is missing",
            f"Free tools for {niche} practitioners are scarce",
            f"Multilingual {niche} content is largely absent",
        ]

        # Try AI enrichment
        try:
            ai = get_ai_client()
            if ai:
                niche_competitors = [
                    CompetitorProfile.from_dict(p).name
                    for p in self._profiles.values()
                    if p.get("niche") == niche
                ]
                prompt = (
                    f"Given these competitors in '{niche}': {niche_competitors or ['unknown']}. "
                    "Identify 3 market gaps. "
                    "Return JSON: {\"gaps\": [\"gap1\", \"gap2\", \"gap3\"]}"
                )
                result = await ai.generate(prompt, model=AIModel.FAST, json_mode=True)
                if result and isinstance(result, dict):
                    gap_templates = result.get("gaps", gap_templates)[:5]
        except Exception as exc:
            logger.debug("find_gaps AI call failed: %s", exc)

        insights: list[CompetitiveInsight] = []
        for i, gap_desc in enumerate(gap_templates[:5]):
            insight = CompetitiveInsight(
                insight_id=str(uuid.uuid4()),
                type="gap",
                description=str(gap_desc),
                priority=min(5, max(1, 5 - i)),
                competitor_id="",
            )
            insights.append(insight)
            self._insights.append(insight.to_dict())

        await self._save()
        return insights

    async def competitive_landscape(self, niche: str) -> dict:
        """Summarize the competitive landscape for a niche."""
        await self._load()
        niche_profiles = [
            CompetitorProfile.from_dict(p)
            for p in self._profiles.values()
            if p.get("niche") == niche
        ]

        total = len(niche_profiles)
        avg_traffic = (
            sum(p.estimated_traffic for p in niche_profiles) / total if total else 0.0
        )

        gap_insights = [
            CompetitiveInsight.from_dict(i)
            for i in self._insights
            if i.get("type") == "gap"
        ]
        threat_insights = [
            CompetitiveInsight.from_dict(i)
            for i in self._insights
            if i.get("type") == "threat"
        ]

        return {
            "total_competitors": total,
            "avg_traffic": round(avg_traffic, 2),
            "top_gaps": [i.description for i in gap_insights[:3]],
            "threats": [i.description for i in threat_insights[:3]],
        }

    def summary(self) -> dict:
        return {
            "total_competitors": len(self._profiles),
            "total_insights": len(self._insights),
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_competitor_monitor_instance: Optional[CompetitorMonitor] = None


def get_competitor_monitor() -> CompetitorMonitor:
    global _competitor_monitor_instance
    if _competitor_monitor_instance is None:
        _competitor_monitor_instance = CompetitorMonitor()
    return _competitor_monitor_instance
