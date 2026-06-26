"""
Ad creative factory — generates multi-platform ad campaigns.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_AD_FACTORY_KEY = "factory:ads:v1"
_AD_FACTORY_TTL = 86400 * 60


class AdPlatform(StrEnum):
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    GOOGLE = "google"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    LINKEDIN = "linkedin"
    TWITTER = "twitter"


class AdObjective(StrEnum):
    AWARENESS = "awareness"
    TRAFFIC = "traffic"
    CONVERSIONS = "conversions"
    RETARGETING = "retargeting"
    LEAD_GEN = "lead_gen"


@dataclass
class AdCreative:
    ad_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    platform: AdPlatform = AdPlatform.FACEBOOK
    objective: AdObjective = AdObjective.CONVERSIONS
    headline: str = ""
    primary_text: str = ""
    cta: str = "Shop Now"
    description: str = ""
    target_audience: str = ""
    estimated_ctr: float = 0.02
    estimated_cpc_usd: float = 0.50
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "ad_id": self.ad_id,
            "platform": self.platform.value,
            "objective": self.objective.value,
            "headline": self.headline,
            "primary_text": self.primary_text,
            "cta": self.cta,
            "description": self.description,
            "target_audience": self.target_audience,
            "estimated_ctr": self.estimated_ctr,
            "estimated_cpc_usd": self.estimated_cpc_usd,
            "created_at": self.created_at,
        }


@dataclass
class AdBatch:
    batch_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    campaign_name: str = ""
    ads: list[AdCreative] = field(default_factory=list)
    total_budget_usd: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "campaign_name": self.campaign_name,
            "ads": [a.to_dict() for a in self.ads],
            "total_budget_usd": self.total_budget_usd,
            "ad_count": len(self.ads),
            "created_at": self.created_at,
        }


class AdFactory:
    def __init__(self) -> None:
        self._batches: list[dict] = []
        self._loaded = False
        self._ai = get_ai_client()

    async def _load(self) -> list[dict]:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_AD_FACTORY_KEY)
                if isinstance(data, list):
                    self._batches = data
            except Exception:
                pass
            self._loaded = True
        return self._batches

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_AD_FACTORY_KEY, self._batches[-100:], ttl_seconds=_AD_FACTORY_TTL)
        except Exception:
            pass

    async def create_ad(
        self,
        product_name: str,
        platform: AdPlatform,
        objective: AdObjective = AdObjective.CONVERSIONS,
        target_audience: str = "",
    ) -> AdCreative:
        headline = ""
        primary_text = ""
        try:
            if self._ai:
                response = await self._ai.complete(
                    system="You are an expert ad copywriter. Write high-converting ad copy.",
                    user=(
                        f"Write a {platform.value} ad for: {product_name}\n"
                        f"Objective: {objective.value}\n"
                        f"Target: {target_audience}\n"
                        "Format: HEADLINE: ...\nBODY: ...\nCTA: ..."
                    ),
                    model=AIModel.CREATIVE,
                    max_tokens=300,
                    agent_name="ad_factory",
                )
                if response.success and response.content:
                    lines = response.content.split("\n")
                    for line in lines:
                        if line.startswith("HEADLINE:"):
                            headline = line.replace("HEADLINE:", "").strip()
                        elif line.startswith("BODY:"):
                            primary_text = line.replace("BODY:", "").strip()
        except Exception:
            pass

        if not headline:
            headline = f"Discover {product_name} Today"
        if not primary_text:
            primary_text = f"Transform your results with {product_name}. Trusted by thousands."

        ctr_by_platform = {
            AdPlatform.FACEBOOK: 0.02,
            AdPlatform.GOOGLE: 0.05,
            AdPlatform.TIKTOK: 0.03,
            AdPlatform.INSTAGRAM: 0.015,
            AdPlatform.LINKEDIN: 0.01,
        }

        return AdCreative(
            platform=platform,
            objective=objective,
            headline=headline,
            primary_text=primary_text,
            cta="Shop Now" if objective == AdObjective.CONVERSIONS else "Learn More",
            description=f"{product_name} — see results fast",
            target_audience=target_audience,
            estimated_ctr=ctr_by_platform.get(platform, 0.02),
            estimated_cpc_usd=0.50 if platform != AdPlatform.LINKEDIN else 5.0,
        )

    async def create_campaign(
        self,
        product_name: str,
        platforms: list[AdPlatform],
        budget_usd: float,
        objective: AdObjective = AdObjective.CONVERSIONS,
        target_audience: str = "",
    ) -> AdBatch:
        await self._load()
        ads: list[AdCreative] = []
        for platform in platforms:
            ad = await self.create_ad(product_name, platform, objective, target_audience)
            ads.append(ad)

        batch = AdBatch(
            campaign_name=f"{product_name} — {objective.value.title()}",
            ads=ads,
            total_budget_usd=budget_usd,
        )
        self._batches.append(batch.to_dict())
        await self._save()
        return batch

    async def create_retargeting_ads(
        self,
        product_name: str,
        abandoned_cart: bool = True,
    ) -> AdBatch:
        platform_list = [AdPlatform.FACEBOOK, AdPlatform.INSTAGRAM, AdPlatform.GOOGLE]
        audience = "website visitors who viewed product but didn't purchase"
        if abandoned_cart:
            audience = "users who added to cart but didn't complete purchase"

        return await self.create_campaign(
            product_name=product_name,
            platforms=platform_list,
            budget_usd=500.0,
            objective=AdObjective.RETARGETING,
            target_audience=audience,
        )

    def summary(self) -> dict:
        total_ads = sum(len(b.get("ads", [])) for b in self._batches)
        return {
            "total_campaigns": len(self._batches),
            "total_ads": total_ads,
        }


_ad_factory_instance: AdFactory | None = None


def get_ad_factory() -> AdFactory:
    global _ad_factory_instance
    if _ad_factory_instance is None:
        _ad_factory_instance = AdFactory()
    return _ad_factory_instance
