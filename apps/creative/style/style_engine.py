from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.memory.redis_client import get_cache

_TTL = 365 * 24 * 3600
_CACHE_KEY = "creative:style:v1"

_NICHE_DEFAULTS: dict[str, dict[str, str]] = {
    "tech": {
        "TONE": "professional and precise",
        "COLOR_PALETTE": "minimal blues and greys",
        "TYPOGRAPHY": "clean sans-serif",
        "IMAGERY": "abstract data visualisations",
        "LANGUAGE": "technical but accessible",
        "PACING": "structured and scannable",
        "EMOTION": "confident and authoritative",
        "STRUCTURE": "logical with clear hierarchy",
    },
    "fashion": {
        "TONE": "aspirational and emotive",
        "COLOR_PALETTE": "bold editorial contrasts",
        "TYPOGRAPHY": "high-fashion serif mixed with grotesque",
        "IMAGERY": "lifestyle and editorial photography",
        "LANGUAGE": "sensory and evocative",
        "PACING": "rhythmic with visual breathing room",
        "EMOTION": "desire and aspiration",
        "STRUCTURE": "magazine-layout inspired",
    },
    "food": {
        "TONE": "warm and inviting",
        "COLOR_PALETTE": "earthy tones with vibrant accents",
        "TYPOGRAPHY": "handwritten accents over clean body",
        "IMAGERY": "close-up food photography",
        "LANGUAGE": "sensory descriptions",
        "PACING": "relaxed and pleasurable",
        "EMOTION": "comfort and delight",
        "STRUCTURE": "story-first with recipe clarity",
    },
    "fitness": {
        "TONE": "energetic and motivating",
        "COLOR_PALETTE": "high-contrast bold colours",
        "TYPOGRAPHY": "strong condensed headlines",
        "IMAGERY": "action and transformation shots",
        "LANGUAGE": "direct and punchy",
        "PACING": "fast and dynamic",
        "EMOTION": "empowerment and determination",
        "STRUCTURE": "challenge-solution-result",
    },
    "default": {
        "TONE": "clear and engaging",
        "COLOR_PALETTE": "balanced neutral palette",
        "TYPOGRAPHY": "readable and modern",
        "IMAGERY": "relevant and authentic",
        "LANGUAGE": "conversational and direct",
        "PACING": "measured with clear breaks",
        "EMOTION": "confident and approachable",
        "STRUCTURE": "introduction-body-call-to-action",
    },
}

_BOLDER_SHIFTS: dict[str, str] = {
    "TONE": "bold and provocative",
    "COLOR_PALETTE": "vivid saturated contrasts",
    "IMAGERY": "striking and unexpected visuals",
    "LANGUAGE": "punchy and provocative",
    "PACING": "intense and rapid-fire",
    "EMOTION": "high-energy and intense",
    "STRUCTURE": "disruptive non-linear flow",
}

_MINIMAL_SHIFTS: dict[str, str] = {
    "TONE": "understated and precise",
    "COLOR_PALETTE": "monochrome with single accent",
    "TYPOGRAPHY": "ultra-clean minimal type",
    "IMAGERY": "white space dominant",
    "LANGUAGE": "concise and essential",
    "PACING": "slow and deliberate",
    "STRUCTURE": "single-column stripped down",
}

_TRENDY_SHIFTS: dict[str, str] = {
    "LANGUAGE": "contemporary slang and cultural references",
    "IMAGERY": "lo-fi aesthetic and UGC style",
    "TYPOGRAPHY": "expressive variable fonts",
    "TONE": "casual and culturally fluent",
    "COLOR_PALETTE": "trend-responsive seasonal palette",
}


class StyleDimension(str, Enum):
    TONE = "TONE"
    COLOR_PALETTE = "COLOR_PALETTE"
    TYPOGRAPHY = "TYPOGRAPHY"
    IMAGERY = "IMAGERY"
    LANGUAGE = "LANGUAGE"
    PACING = "PACING"
    EMOTION = "EMOTION"
    STRUCTURE = "STRUCTURE"


@dataclass
class StyleProfile:
    profile_id: str
    name: str
    niche: str
    dimensions: dict[str, str]
    novelty_score: float
    coherence_score: float
    last_evolved_at: float
    evolution_count: int
    created_at: float

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "niche": self.niche,
            "dimensions": self.dimensions,
            "novelty_score": self.novelty_score,
            "coherence_score": self.coherence_score,
            "last_evolved_at": self.last_evolved_at,
            "evolution_count": self.evolution_count,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StyleProfile:
        return cls(
            profile_id=data["profile_id"],
            name=data["name"],
            niche=data["niche"],
            dimensions=data["dimensions"],
            novelty_score=data.get("novelty_score", 0.5),
            coherence_score=data.get("coherence_score", 0.8),
            last_evolved_at=data.get("last_evolved_at", time.time()),
            evolution_count=data.get("evolution_count", 0),
            created_at=data.get("created_at", time.time()),
        )


class StyleEngine:
    def __init__(self) -> None:
        self._profiles: dict[str, dict] = {}
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, dict):
                self._profiles = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        self._loaded = True
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._profiles, ttl_seconds=_TTL)
        except Exception:
            pass

    async def create_profile(
        self,
        name: str,
        niche: str,
        base_style: dict | None = None,
    ) -> StyleProfile:
        await self._load()
        defaults = _NICHE_DEFAULTS.get(niche.lower(), _NICHE_DEFAULTS["default"])
        dimensions = {dim.value: defaults.get(dim.value, "balanced") for dim in StyleDimension}
        if base_style:
            dimensions.update(base_style)
        profile = StyleProfile(
            profile_id=str(uuid.uuid4()),
            name=name,
            niche=niche,
            dimensions=dimensions,
            novelty_score=0.5,
            coherence_score=0.85,
            last_evolved_at=time.time(),
            evolution_count=0,
            created_at=time.time(),
        )
        self._profiles[profile.profile_id] = profile.to_dict()
        await self._save()
        return profile

    async def evolve_style(
        self, profile_id: str, direction: str = "bolder"
    ) -> StyleProfile:
        await self._load()
        raw = self._profiles.get(profile_id)
        if not raw:
            raise ValueError(f"Profile {profile_id} not found")
        profile = StyleProfile.from_dict(raw)
        shifts: dict[str, str]
        if direction == "bolder":
            shifts = _BOLDER_SHIFTS
        elif direction == "minimal":
            shifts = _MINIMAL_SHIFTS
        elif direction == "trendy":
            shifts = _TRENDY_SHIFTS
        else:
            shifts = _BOLDER_SHIFTS
        for dim_key, new_val in shifts.items():
            profile.dimensions[dim_key] = new_val
        profile.evolution_count += 1
        profile.last_evolved_at = time.time()
        profile.novelty_score = min(1.0, profile.novelty_score + 0.1)
        profile.coherence_score = max(0.5, profile.coherence_score - 0.02)
        self._profiles[profile_id] = profile.to_dict()
        await self._save()
        return profile

    async def check_novelty(self, profile_id: str, content: str) -> dict:
        await self._load()
        raw = self._profiles.get(profile_id)
        if not raw:
            return {"novelty_score": 0.5, "detected_cliches": [], "freshness_tips": []}
        cliches = [
            "in today's fast-paced world",
            "game-changer",
            "revolutionary",
            "seamless experience",
            "cutting-edge",
            "innovative solution",
            "best practices",
            "leverage",
            "synergy",
            "paradigm shift",
        ]
        content_lower = content.lower()
        detected = [c for c in cliches if c in content_lower]
        cliche_penalty = len(detected) * 0.08
        profile = StyleProfile.from_dict(raw)
        novelty_score = max(0.0, min(1.0, profile.novelty_score - cliche_penalty))
        tips: list[str] = []
        if detected:
            tips.append("Replace overused phrases with specific data or anecdotes")
        if len(content) < 200:
            tips.append("Expand with concrete examples or proof points")
        tips.append("Use unexpected analogies drawn from outside your niche")
        if novelty_score < 0.4:
            tips.append("Start with a counterintuitive statement to hook readers")
        return {
            "novelty_score": round(novelty_score, 3),
            "detected_cliches": detected,
            "freshness_tips": tips,
        }

    async def style_consistency_audit(
        self, profile_id: str, contents: list[str]
    ) -> dict:
        await self._load()
        if not contents:
            return {
                "consistency_score": 1.0,
                "inconsistencies": [],
                "recommendation": "No content provided for audit.",
            }
        raw = self._profiles.get(profile_id)
        if not raw:
            return {
                "consistency_score": 0.0,
                "inconsistencies": ["Profile not found"],
                "recommendation": "Create a style profile first.",
            }
        profile = StyleProfile.from_dict(raw)
        tone = profile.dimensions.get("TONE", "")
        inconsistencies: list[str] = []
        formal_markers = ["however", "therefore", "furthermore", "henceforth"]
        casual_markers = ["lol", "omg", "tbh", "ngl", "gonna", "wanna"]
        formal_counts = [
            sum(1 for m in formal_markers if m in c.lower()) for c in contents
        ]
        casual_counts = [
            sum(1 for m in casual_markers if m in c.lower()) for c in contents
        ]
        if any(f > 0 for f in formal_counts) and any(c > 0 for c in casual_counts):
            inconsistencies.append(
                "Mixed formal and casual register detected across content pieces"
            )
        lengths = [len(c) for c in contents]
        if max(lengths) > min(lengths) * 4 and len(contents) > 1:
            inconsistencies.append(
                "Significant length variation suggests inconsistent content depth"
            )
        if "professional" in tone and any(c > 0 for c in casual_counts):
            inconsistencies.append(
                "Casual language found but profile tone is professional"
            )
        consistency_score = max(0.0, 1.0 - len(inconsistencies) * 0.2)
        rec = (
            "Content is well-aligned with style profile."
            if not inconsistencies
            else "Standardise voice and length across all content pieces."
        )
        return {
            "consistency_score": round(consistency_score, 3),
            "inconsistencies": inconsistencies,
            "recommendation": rec,
        }

    def summary(self) -> dict:
        if not self._profiles:
            return {"total_profiles": 0, "avg_novelty_score": 0.0}
        scores = [p.get("novelty_score", 0.5) for p in self._profiles.values()]
        avg = sum(scores) / len(scores) if scores else 0.0
        return {
            "total_profiles": len(self._profiles),
            "avg_novelty_score": round(avg, 3),
        }


_style_engine_instance: StyleEngine | None = None


def get_style_engine() -> StyleEngine:
    global _style_engine_instance
    if _style_engine_instance is None:
        _style_engine_instance = StyleEngine()
    return _style_engine_instance
