"""ClientMemory — Customer profiles, interaction history, segmentation, and personalization."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_KEY = "memory:clients:v1"
_TTL = 86400 * 365


@dataclass
class ClientProfile:
    profile_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    email: str = ""
    company: str = ""
    industry: str = ""
    total_spent_usd: float = 0.0
    ltv_estimate: float = 0.0
    purchase_count: int = 0
    preferred_products: list = field(default_factory=list)
    communication_preferences: dict = field(default_factory=dict)
    pain_points: list = field(default_factory=list)
    segment: str = "standard"
    last_interaction_at: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return dict(self.__dict__.items())


@dataclass
class ClientInteraction:
    interaction_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    profile_id: str = ""
    interaction_type: str = ""
    summary: str = ""
    sentiment: str = "neutral"
    value_usd: float = 0.0
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return dict(self.__dict__.items())


class ClientMemory:
    def __init__(self) -> None:
        self._profiles: list[dict] = []
        self._interactions: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._profiles = data.get("profiles", [])
                    self._interactions = data.get("interactions", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _KEY,
                {"profiles": self._profiles[-1000:], "interactions": self._interactions[-2000:]},
                ttl_seconds=_TTL,
            )
        except Exception:
            pass

    async def upsert_profile(
        self, name: str, email: str, company: str = "", industry: str = ""
    ) -> ClientProfile:
        await self._load()
        for i, p in enumerate(self._profiles):
            if p.get("email") == email:
                self._profiles[i].update({"name": name, "company": company, "industry": industry})
                await self._save()
                return ClientProfile(
                    **{
                        k: v
                        for k, v in self._profiles[i].items()
                        if k in ClientProfile.__dataclass_fields__
                    }
                )
        profile = ClientProfile(
            name=name,
            email=email,
            company=company,
            industry=industry,
            ltv_estimate=0.0,
            last_interaction_at=time.time(),
        )
        self._profiles.append(profile.to_dict())
        await self._save()
        return profile

    async def record_interaction(
        self, profile_id: str, interaction_type: str, summary: str, value_usd: float = 0.0
    ) -> ClientInteraction:
        await self._load()
        sentiment = "neutral"
        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system="Sentiment classifier. Reply with ONE word: positive, neutral, or negative.",
                user=f"Sentiment of: '{summary[:200]}'",
                model=AIModel.FAST,
                max_tokens=10,
            )
            if resp.success and resp.content:
                word = resp.content.strip().lower()
                if word in ("positive", "neutral", "negative"):
                    sentiment = word
        except Exception:
            pass

        interaction = ClientInteraction(
            profile_id=profile_id,
            interaction_type=interaction_type,
            summary=summary,
            sentiment=sentiment,
            value_usd=value_usd,
        )
        self._interactions.append(interaction.to_dict())

        for i, p in enumerate(self._profiles):
            if p.get("profile_id") == profile_id:
                self._profiles[i]["last_interaction_at"] = time.time()
                if interaction_type == "purchase":
                    self._profiles[i]["total_spent_usd"] = p.get("total_spent_usd", 0) + value_usd
                    self._profiles[i]["purchase_count"] = p.get("purchase_count", 0) + 1
                break
        await self._save()
        return interaction

    async def segment_client(self, profile_id: str) -> str:
        await self._load()
        for i, p in enumerate(self._profiles):
            if p.get("profile_id") == profile_id:
                spent = p.get("total_spent_usd", 0)
                purchases = p.get("purchase_count", 0)
                last = p.get("last_interaction_at", 0)
                days_since = (time.time() - last) / 86400 if last else 999

                if spent > 1000 or purchases > 10:
                    seg = "vip"
                elif spent > 300:
                    seg = "high_value"
                elif days_since > 180:
                    seg = "churned"
                elif days_since > 90:
                    seg = "at_risk"
                else:
                    seg = "standard"

                self._profiles[i]["segment"] = seg
                await self._save()
                return seg
        return "standard"

    async def personalize_offer(self, profile_id: str, available_products: list) -> dict:
        await self._load()
        profile = next((p for p in self._profiles if p.get("profile_id") == profile_id), {})
        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system="Product recommendation engine.",
                user=f"Client: {profile.get('name')}, spent ${profile.get('total_spent_usd',0)}, segment: {profile.get('segment')}. Products: {available_products[:5]}. Pick best offer.",
                model=AIModel.FAST,
                max_tokens=100,
            )
            if resp.success and resp.content:
                return {
                    "recommended_product": (
                        available_products[0] if available_products else "premium_plan"
                    ),
                    "offer": "15% loyalty discount",
                    "reasoning": resp.content[:150],
                }
        except Exception:
            pass
        return {
            "recommended_product": available_products[0] if available_products else "starter_plan",
            "offer": "10% discount",
            "reasoning": "Based on purchase history",
        }

    def get_profile(self, email: str) -> dict | None:
        return next((p for p in self._profiles if p.get("email") == email), None)

    def vip_clients(self) -> list[dict]:
        return [p for p in self._profiles if p.get("segment") == "vip"]

    def at_risk_clients(self) -> list[dict]:
        return [p for p in self._profiles if p.get("segment") in ("at_risk", "churned")]

    def client_memory_summary(self) -> dict:
        by_segment: dict = {}
        for p in self._profiles:
            seg = p.get("segment", "standard")
            by_segment[seg] = by_segment.get(seg, 0) + 1
        return {
            "total_profiles": len(self._profiles),
            "total_interactions": len(self._interactions),
            "by_segment": by_segment,
            "vip_count": by_segment.get("vip", 0),
            "total_ltv": round(sum(p.get("total_spent_usd", 0) for p in self._profiles), 2),
        }


_instance: ClientMemory | None = None


def get_client_memory() -> ClientMemory:
    global _instance
    if _instance is None:
        _instance = ClientMemory()
    return _instance
