from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_TTL = 365 * 24 * 3600
_CACHE_KEY = "creative:identity:v1"

_NICHE_ARCHETYPES: dict[str, list[str]] = {
    "tech": [
        "How-to tutorials",
        "Tool reviews",
        "Industry analysis",
        "Case studies",
        "Opinion pieces",
    ],
    "fashion": [
        "Lookbooks",
        "Trend forecasts",
        "Style guides",
        "Behind-the-scenes",
        "Brand spotlights",
    ],
    "food": [
        "Recipe features",
        "Restaurant reviews",
        "Ingredient deep-dives",
        "Chef interviews",
        "Technique guides",
    ],
    "fitness": [
        "Workout programmes",
        "Transformation stories",
        "Nutrition breakdowns",
        "Coach Q&As",
        "Equipment reviews",
    ],
    "finance": [
        "Market commentary",
        "Personal finance guides",
        "Investment case studies",
        "Myth-busting",
        "Tool comparisons",
    ],
    "default": [
        "Educational guides",
        "Opinion pieces",
        "Case studies",
        "How-tos",
        "Community spotlights",
    ],
}

_NICHE_VOICES: dict[str, str] = {
    "tech": "direct, data-driven, empowering",
    "fashion": "aspirational, visual, culturally aware",
    "food": "warm, sensory, community-focused",
    "fitness": "motivating, no-nonsense, results-oriented",
    "finance": "trustworthy, clear, evidence-based",
    "default": "authentic, practical, human",
}

_NICHE_VISUAL: dict[str, str] = {
    "tech": "clean lines, monochrome base with one accent colour, data-forward layouts",
    "fashion": "editorial photography, generous white space, high-contrast typography",
    "food": "warm tones, close-up textures, hand-crafted feel",
    "fitness": "bold colours, dynamic angles, motivational typography",
    "finance": "structured grids, trust-inducing blues, clear charts",
    "default": "balanced composition, approachable palette, consistent spacing",
}

_NICHE_AVOID: dict[str, list[str]] = {
    "tech": ["over-hyped buzzwords", "vague product promises", "unexplained jargon"],
    "fashion": [
        "generic stock photography",
        "trend-chasing without editorial voice",
        "unclear brand positioning",
    ],
    "food": ["inauthentic sourcing claims", "over-styled unrealistic shots", "recipe vagueness"],
    "fitness": [
        "before/after without context",
        "miracle-claim language",
        "generic motivation quotes",
    ],
    "finance": ["get-rich-quick framing", "unverified statistics", "fear-based marketing"],
    "default": ["AI clichés", "vague benefit claims", "generic stock imagery"],
}


@dataclass
class CreativeEvolution:
    evolution_id: str
    trigger: str
    changes: dict
    novelty_delta: float
    timestamp: float

    def to_dict(self) -> dict:
        return {
            "evolution_id": self.evolution_id,
            "trigger": self.trigger,
            "changes": self.changes,
            "novelty_delta": self.novelty_delta,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CreativeEvolution:
        return cls(
            evolution_id=data["evolution_id"],
            trigger=data["trigger"],
            changes=data.get("changes", {}),
            novelty_delta=data.get("novelty_delta", 0.1),
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class CreativeIdentity:
    identity_id: str
    brand_name: str
    niche: str
    voice_signature: str
    visual_signature: str
    content_archetypes: list[str]
    avoid_patterns: list[str]
    evolution_history: list[CreativeEvolution]
    novelty_score: float
    last_refreshed_at: float
    created_at: float

    def to_dict(self) -> dict:
        return {
            "identity_id": self.identity_id,
            "brand_name": self.brand_name,
            "niche": self.niche,
            "voice_signature": self.voice_signature,
            "visual_signature": self.visual_signature,
            "content_archetypes": self.content_archetypes,
            "avoid_patterns": self.avoid_patterns,
            "evolution_history": [e.to_dict() for e in self.evolution_history],
            "novelty_score": self.novelty_score,
            "last_refreshed_at": self.last_refreshed_at,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CreativeIdentity:
        evolutions = [CreativeEvolution.from_dict(e) for e in data.get("evolution_history", [])]
        return cls(
            identity_id=data["identity_id"],
            brand_name=data["brand_name"],
            niche=data["niche"],
            voice_signature=data["voice_signature"],
            visual_signature=data["visual_signature"],
            content_archetypes=data.get("content_archetypes", []),
            avoid_patterns=data.get("avoid_patterns", []),
            evolution_history=evolutions,
            novelty_score=data.get("novelty_score", 0.5),
            last_refreshed_at=data.get("last_refreshed_at", time.time()),
            created_at=data.get("created_at", time.time()),
        )


class CreativeIdentityManager:
    def __init__(self) -> None:
        self._identities: dict[str, dict] = {}
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, dict):
                self._identities = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        self._loaded = True
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._identities, ttl_seconds=_TTL)
        except Exception:
            pass

    async def create_identity(self, brand_name: str, niche: str) -> CreativeIdentity:
        await self._load()
        key = niche.lower()
        voice = _NICHE_VOICES.get(key, _NICHE_VOICES["default"])
        visual = _NICHE_VISUAL.get(key, _NICHE_VISUAL["default"])
        archetypes = _NICHE_ARCHETYPES.get(key, _NICHE_ARCHETYPES["default"])
        avoid = _NICHE_AVOID.get(key, _NICHE_AVOID["default"])
        identity = CreativeIdentity(
            identity_id=str(uuid.uuid4()),
            brand_name=brand_name,
            niche=niche,
            voice_signature=voice,
            visual_signature=visual,
            content_archetypes=archetypes,
            avoid_patterns=avoid,
            evolution_history=[],
            novelty_score=0.5,
            last_refreshed_at=time.time(),
            created_at=time.time(),
        )
        self._identities[identity.identity_id] = identity.to_dict()
        await self._save()
        return identity

    async def refresh_identity(self, identity_id: str, inspiration: str = "") -> CreativeIdentity:
        await self._load()
        raw = self._identities.get(identity_id)
        if not raw:
            raise ValueError(f"Identity {identity_id} not found")
        identity = CreativeIdentity.from_dict(raw)
        changes: dict = {}
        old_novelty = identity.novelty_score
        if inspiration:
            changes["inspiration_applied"] = inspiration
            changes["voice_refined"] = (
                f"{identity.voice_signature}, inspired by: {inspiration[:80]}"
            )
            identity.voice_signature = changes["voice_refined"]
        identity.novelty_score = min(1.0, identity.novelty_score + 0.1)
        identity.last_refreshed_at = time.time()
        novelty_delta = round(identity.novelty_score - old_novelty, 3)
        evolution = CreativeEvolution(
            evolution_id=str(uuid.uuid4()),
            trigger=inspiration or "manual refresh",
            changes=changes,
            novelty_delta=novelty_delta,
            timestamp=time.time(),
        )
        identity.evolution_history.append(evolution)
        self._identities[identity_id] = identity.to_dict()
        await self._save()
        return identity

    async def get_identity(self, identity_id: str) -> CreativeIdentity | None:
        await self._load()
        raw = self._identities.get(identity_id)
        if not raw:
            return None
        return CreativeIdentity.from_dict(raw)

    async def apply_identity(self, identity_id: str, content: str) -> str:
        await self._load()
        raw = self._identities.get(identity_id)
        if not raw:
            return content
        identity = CreativeIdentity.from_dict(raw)
        try:
            ai = get_ai_client()
            prompt = (
                f"Rewrite the following content to match this brand voice: '{identity.voice_signature}'. "
                f"The brand is {identity.brand_name} in the {identity.niche} niche. "
                f"Avoid these patterns: {', '.join(identity.avoid_patterns)}. "
                f"Keep the same core message.\n\nContent:\n{content}"
            )
            result = await ai.complete(prompt, model=AIModel.CREATIVE)
            if result and result.success and result.content and len(result.content) > 20:
                return result.content.strip()
        except Exception:
            pass
        # Rule-based fallback: prepend voice signal
        return f"[{identity.voice_signature.split(',')[0].strip().capitalize()} voice] {content}"

    def summary(self) -> dict:
        if not self._identities:
            return {"total_identities": 0, "avg_novelty_score": 0.0}
        scores = [v.get("novelty_score", 0.5) for v in self._identities.values()]
        avg = sum(scores) / len(scores) if scores else 0.0
        return {
            "total_identities": len(self._identities),
            "avg_novelty_score": round(avg, 3),
        }


_creative_identity_manager_instance: CreativeIdentityManager | None = None


def get_creative_identity_manager() -> CreativeIdentityManager:
    global _creative_identity_manager_instance
    if _creative_identity_manager_instance is None:
        _creative_identity_manager_instance = CreativeIdentityManager()
    return _creative_identity_manager_instance
