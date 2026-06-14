"""
AudienceSegmenter — Ad targeting audience creation and CAC estimation.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_KEY = "ads:audiences:v1"
_TTL = 86400 * 60

_CPM_BY_PLATFORM = {
    "meta": (8.0, 15.0),
    "google": (2.0, 8.0),
    "tiktok": (6.0, 12.0),
}


@dataclass
class AudienceSegment:
    segment_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    criteria: dict = field(default_factory=dict)
    user_count: int = 0
    platforms: list = field(default_factory=list)
    estimated_cpm: float = 10.0
    interest_keywords: list = field(default_factory=list)
    exclusions: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "name": self.name,
            "criteria": self.criteria,
            "user_count": self.user_count,
            "platforms": self.platforms,
            "estimated_cpm": self.estimated_cpm,
            "interest_keywords": self.interest_keywords,
            "exclusions": self.exclusions,
            "created_at": self.created_at,
        }


class AudienceSegmenter:
    def __init__(self) -> None:
        self._segments: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, list):
                    self._segments = data
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, self._segments[-500:], ttl_seconds=_TTL)
        except Exception:
            pass

    async def create_segment(
        self,
        name: str,
        criteria: dict,
        platforms: list[str] = ["meta"],
    ) -> AudienceSegment:
        await self._load()
        specificity = len(criteria)
        cpm_range = _CPM_BY_PLATFORM.get(platforms[0] if platforms else "meta", (8.0, 15.0))
        cpm = cpm_range[0] + (cpm_range[1] - cpm_range[0]) * min(1.0, specificity / 5)
        segment = AudienceSegment(
            name=name,
            criteria=criteria,
            user_count=criteria.get("estimated_size", 50000),
            platforms=platforms,
            estimated_cpm=round(cpm, 2),
        )
        self._segments.append(segment.to_dict())
        await self._save()
        return segment

    async def suggest_lookalike(
        self, seed_segment: AudienceSegment, similarity_pct: float = 0.02
    ) -> AudienceSegment:
        await self._load()
        lookalike = AudienceSegment(
            name=f"Lookalike {similarity_pct*100:.0f}% — {seed_segment.name}",
            criteria={"source": seed_segment.segment_id, "similarity": similarity_pct},
            user_count=int(seed_segment.user_count / similarity_pct),
            platforms=seed_segment.platforms,
            estimated_cpm=seed_segment.estimated_cpm * 0.8,
            interest_keywords=seed_segment.interest_keywords,
        )
        self._segments.append(lookalike.to_dict())
        await self._save()
        return lookalike

    async def generate_interest_targeting(self, product: str, niche: str) -> list[str]:
        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system="You are a Facebook Ads expert.",
                user=f"List 15 Facebook/Instagram interest targeting keywords for '{product}' in the '{niche}' niche. One per line, no bullets or numbers.",
                model=AIModel.FAST,
                max_tokens=300,
            )
            if resp.success and resp.content:
                return [l.strip() for l in resp.content.split("\n") if l.strip()][:15]
        except Exception:
            pass
        return [
            f"{niche}", f"online {niche}", f"{product} tips",
            "entrepreneurship", "passive income", "digital marketing",
            "online business", "ecommerce", "social media marketing",
            "content creation", "AI tools", "productivity",
            "make money online", "side hustle", "business growth",
        ]

    def generate_exclusion_audiences(self) -> list[str]:
        return [
            "recent_purchasers_30d",
            "current_subscribers",
            "employees",
            "bounced_users",
            "already_converted",
        ]

    def cac_estimate(
        self,
        segment: AudienceSegment,
        product_price: float,
        expected_cvr: float = 0.02,
    ) -> dict:
        ctr = 0.015
        cpc = segment.estimated_cpm / (ctr * 1000)
        cac = cpc / max(expected_cvr, 0.001)
        profitable = cac < product_price * 0.4
        return {
            "cpm": segment.estimated_cpm,
            "ctr": ctr,
            "cpc": round(cpc, 2),
            "cac": round(cac, 2),
            "break_even_price": round(cac * 2.5, 2),
            "profitable": profitable,
            "platform": segment.platforms[0] if segment.platforms else "meta",
        }

    def segment_analytics(self) -> dict:
        by_platform: dict[str, int] = {}
        for s in self._segments:
            for p in s.get("platforms", []):
                by_platform[p] = by_platform.get(p, 0) + 1
        avg_cpm = (
            sum(s.get("estimated_cpm", 0) for s in self._segments) / len(self._segments)
            if self._segments else 0.0
        )
        return {
            "total_segments": len(self._segments),
            "by_platform": by_platform,
            "avg_cpm": round(avg_cpm, 2),
        }


_instance: Optional[AudienceSegmenter] = None


def get_audience_segmenter() -> AudienceSegmenter:
    global _instance
    if _instance is None:
        _instance = AudienceSegmenter()
    return _instance
