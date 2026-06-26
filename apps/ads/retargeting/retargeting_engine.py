"""
Retargeting Engine — Manages retargeting audiences, campaigns, and optimization.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_RETARGETING_KEY = "ads:retargeting:v1"
_RETARGETING_TTL = 86400 * 60  # 60 days


@dataclass
class RetargetingAudience:
    audience_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    audience_type: str = (
        "product_viewers"  # "cart_abandoners"|"product_viewers"|"purchasers"|"email_subscribers"|"lookalike"
    )
    user_ids: list[str] = field(default_factory=list)
    size: int = 0
    platforms: list[str] = field(default_factory=list)
    estimated_roas: float = 2.5
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "audience_id": self.audience_id,
            "name": self.name,
            "audience_type": self.audience_type,
            "user_ids": self.user_ids,
            "size": self.size,
            "platforms": self.platforms,
            "estimated_roas": self.estimated_roas,
            "created_at": self.created_at,
        }


@dataclass
class RetargetingCampaign:
    campaign_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    audience_id: str = ""
    audience_type: str = ""
    ad_copy: str = ""
    headline: str = ""
    image_url: str = ""
    budget_daily_usd: float = 0.0
    platform: str = "meta"  # "meta"|"google"|"tiktok"
    status: str = "draft"  # "draft"|"active"|"paused"|"ended"
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    spend_usd: float = 0.0
    revenue_usd: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "name": self.name,
            "audience_id": self.audience_id,
            "audience_type": self.audience_type,
            "ad_copy": self.ad_copy,
            "headline": self.headline,
            "image_url": self.image_url,
            "budget_daily_usd": self.budget_daily_usd,
            "platform": self.platform,
            "status": self.status,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "conversions": self.conversions,
            "spend_usd": self.spend_usd,
            "revenue_usd": self.revenue_usd,
            "ctr": self.ctr(),
            "roas": self.roas(),
            "cac": self.cac(),
            "created_at": self.created_at,
        }

    def ctr(self) -> float:
        return self.clicks / self.impressions if self.impressions > 0 else 0.0

    def roas(self) -> float:
        return self.revenue_usd / self.spend_usd if self.spend_usd > 0 else 0.0

    def cac(self) -> float:
        return self.spend_usd / self.conversions if self.conversions > 0 else 0.0


_ROAS_BY_AUDIENCE: dict[str, float] = {
    "cart_abandoners": 4.5,
    "product_viewers": 3.0,
    "purchasers": 5.0,
    "email_subscribers": 3.5,
    "lookalike": 2.5,
}

_DEFAULT_COPY: dict[str, str] = {
    "cart_abandoners": "You left {product} behind. Complete your order + 10% off today only.",
    "product_viewers": "Still thinking about {product}? Here's what others are saying...",
    "purchasers": "Love {product}? Complete the collection.",
    "email_subscribers": "Exclusive offer for subscribers: Save on {product} today.",
    "lookalike": "Discover {product} — join thousands of happy customers.",
}

_DEFAULT_HEADLINE: dict[str, str] = {
    "cart_abandoners": "Don't Miss Out — Your Cart is Waiting",
    "product_viewers": "See Why Everyone Loves {product}",
    "purchasers": "You'll Love This Too",
    "email_subscribers": "Your Exclusive Deal is Here",
    "lookalike": "{product} — Built for You",
}


class RetargetingEngine:
    def __init__(self) -> None:
        self._audiences: list[dict] = []
        self._campaigns: list[dict] = []
        self._loaded = False
        self._ai = get_ai_client()

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_RETARGETING_KEY)
                if isinstance(data, dict):
                    self._audiences = data.get("audiences", [])
                    self._campaigns = data.get("campaigns", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _RETARGETING_KEY,
                {
                    "audiences": self._audiences[-200:],
                    "campaigns": self._campaigns[-200:],
                },
                ttl_seconds=_RETARGETING_TTL,
            )
        except Exception:
            pass

    async def create_audience(
        self,
        name: str,
        audience_type: str,
        user_ids: list[str],
        platforms: list[str] = None,
    ) -> RetargetingAudience:
        if platforms is None:
            platforms = ["meta", "google"]
        await self._load()

        audience = RetargetingAudience(
            name=name,
            audience_type=audience_type,
            user_ids=user_ids,
            size=len(user_ids),
            platforms=platforms,
            estimated_roas=_ROAS_BY_AUDIENCE.get(audience_type, 2.5),
        )

        self._audiences.append(audience.to_dict())
        await self._save()
        return audience

    async def create_campaign(
        self,
        audience: RetargetingAudience,
        product_name: str,
        budget_daily: float,
        platform: str = "meta",
    ) -> RetargetingCampaign:
        await self._load()

        audience_type = audience.audience_type
        ad_copy = _DEFAULT_COPY.get(audience_type, "Discover {product} today.").format(
            product=product_name
        )
        headline = _DEFAULT_HEADLINE.get(audience_type, "Get {product} Now").format(
            product=product_name
        )

        # Try AI enhancement
        try:
            if self._ai:
                prompt_context = {
                    "cart_abandoners": f"Cart abandonment retargeting for {product_name}. Offer urgency and a 10% discount.",
                    "product_viewers": f"Product viewer retargeting for {product_name}. Use social proof and FOMO.",
                    "purchasers": f"Cross-sell retargeting for existing {product_name} buyers. Upsell complementary items.",
                }.get(audience_type, f"Retargeting ad for {product_name} on {platform}.")

                response = await self._ai.complete(
                    system=(
                        "You are an expert performance marketer. Write retargeting ad copy. "
                        "Format:\nHEADLINE: ...\nCOPY: ..."
                    ),
                    user=prompt_context,
                    model=AIModel.CREATIVE,
                    max_tokens=200,
                )
                if response.success and response.content:
                    lines = response.content.strip().split("\n")
                    for line in lines:
                        if line.upper().startswith("HEADLINE:"):
                            ai_headline = line[9:].strip()
                            if ai_headline:
                                headline = ai_headline
                        elif line.upper().startswith("COPY:"):
                            ai_copy = line[5:].strip()
                            if ai_copy:
                                ad_copy = ai_copy
        except Exception:
            pass

        campaign = RetargetingCampaign(
            name=f"{audience_type.replace('_', ' ').title()} — {product_name} ({platform})",
            audience_id=audience.audience_id,
            audience_type=audience_type,
            ad_copy=ad_copy,
            headline=headline,
            budget_daily_usd=budget_daily,
            platform=platform,
            status="draft",
        )

        self._campaigns.append(campaign.to_dict())
        await self._save()
        return campaign

    async def record_metrics(
        self,
        campaign_id: str,
        impressions: int = 0,
        clicks: int = 0,
        conversions: int = 0,
        spend: float = 0.0,
        revenue: float = 0.0,
    ) -> bool:
        await self._load()

        for i, c in enumerate(self._campaigns):
            if c.get("campaign_id") == campaign_id:
                self._campaigns[i]["impressions"] = c.get("impressions", 0) + impressions
                self._campaigns[i]["clicks"] = c.get("clicks", 0) + clicks
                self._campaigns[i]["conversions"] = c.get("conversions", 0) + conversions
                self._campaigns[i]["spend_usd"] = c.get("spend_usd", 0.0) + spend
                self._campaigns[i]["revenue_usd"] = c.get("revenue_usd", 0.0) + revenue

                # Recalculate derived metrics
                imp = self._campaigns[i]["impressions"]
                clk = self._campaigns[i]["clicks"]
                conv = self._campaigns[i]["conversions"]
                sp = self._campaigns[i]["spend_usd"]
                rev = self._campaigns[i]["revenue_usd"]
                self._campaigns[i]["ctr"] = clk / imp if imp > 0 else 0.0
                self._campaigns[i]["roas"] = rev / sp if sp > 0 else 0.0
                self._campaigns[i]["cac"] = sp / conv if conv > 0 else 0.0

                await self._save()
                return True
        return False

    async def optimize_budget(
        self,
        campaigns: list[RetargetingCampaign],
    ) -> list[dict]:
        """Recommend budget changes based on ROAS."""
        recommendations: list[dict] = []

        for campaign in campaigns:
            roas = campaign.roas()
            current_budget = campaign.budget_daily_usd

            if roas > 3.0:
                new_budget = round(current_budget * 1.2, 2)
                action = "increase"
                rationale = f"ROAS of {roas:.2f}x exceeds 3.0x threshold — scale up 20%"
            elif roas < 1.5 and campaign.spend_usd > 0:
                new_budget = 0.0
                action = "pause"
                rationale = f"ROAS of {roas:.2f}x below 1.5x threshold — pause to prevent losses"
            else:
                new_budget = current_budget
                action = "maintain"
                rationale = f"ROAS of {roas:.2f}x is acceptable — maintain current budget"

            recommendations.append(
                {
                    "campaign_id": campaign.campaign_id,
                    "action": action,
                    "recommended_budget": new_budget,
                    "current_budget": current_budget,
                    "current_roas": roas,
                    "rationale": rationale,
                }
            )

        return recommendations

    async def cart_abandonment_sequence(
        self,
        cart_items: list[dict],
        user_id: str,
    ) -> list[dict]:
        """Create 3-ad retargeting sequence for cart abandoners."""
        product_names = [
            item.get("name", item.get("product", "your item")) for item in cart_items[:3]
        ]
        product_str = ", ".join(product_names) if product_names else "your items"

        sequence = [
            {
                "sequence": 1,
                "delay_hours": 0,
                "trigger": "immediate",
                "headline": "You Left Something Behind",
                "ad_copy": f"Your cart is still waiting! {product_str} — ready when you are.",
                "discount": None,
                "urgency": "low",
                "user_id": user_id,
            },
            {
                "sequence": 2,
                "delay_hours": 24,
                "trigger": "24h_followup",
                "headline": "Still Interested? Here's 5% Off",
                "ad_copy": f"Complete your order for {product_str} and save 5% with code COMEBACK5.",
                "discount": "5%",
                "urgency": "medium",
                "user_id": user_id,
            },
            {
                "sequence": 3,
                "delay_hours": 72,
                "trigger": "72h_final",
                "headline": "Last Chance — 10% Off + Limited Stock",
                "ad_copy": (
                    f"Only a few left! Grab {product_str} now with 10% off (code SAVE10). "
                    "Offer expires in 24 hours."
                ),
                "discount": "10%",
                "urgency": "high",
                "user_id": user_id,
            },
        ]

        return sequence

    def campaign_analytics(self) -> dict:
        """Aggregate analytics across all campaigns."""
        total = len(self._campaigns)
        active = sum(1 for c in self._campaigns if c.get("status") == "active")
        total_spend = sum(c.get("spend_usd", 0.0) for c in self._campaigns)
        total_revenue = sum(c.get("revenue_usd", 0.0) for c in self._campaigns)
        total_conversions = sum(c.get("conversions", 0) for c in self._campaigns)

        avg_roas = total_revenue / total_spend if total_spend > 0 else 0.0
        total_cac = total_spend / total_conversions if total_conversions > 0 else 0.0

        return {
            "total_campaigns": total,
            "active_campaigns": active,
            "total_spend": round(total_spend, 2),
            "total_revenue": round(total_revenue, 2),
            "avg_roas": round(avg_roas, 2),
            "total_cac": round(total_cac, 2),
        }

    def top_performing_campaigns(self, limit: int = 5) -> list[dict]:
        """Return top campaigns by ROAS."""
        sorted_campaigns = sorted(
            self._campaigns,
            key=lambda c: (
                c.get("roas", c.get("revenue_usd", 0.0) / c.get("spend_usd", 1.0))
                if c.get("spend_usd", 0) > 0
                else 0.0
            ),
            reverse=True,
        )
        return sorted_campaigns[:limit]


_retargeting_engine_instance: RetargetingEngine | None = None


def get_retargeting_engine() -> RetargetingEngine:
    global _retargeting_engine_instance
    if _retargeting_engine_instance is None:
        _retargeting_engine_instance = RetargetingEngine()
    return _retargeting_engine_instance
