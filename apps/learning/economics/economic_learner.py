from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache

_CACHE_KEY = "learning:economics:v1"
_CACHE_TTL = 86400 * 365  # 365 days


@dataclass
class CampaignOutcome:
    campaign_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    channel: str = ""
    spend_usd: float = 0.0
    revenue_usd: float = 0.0
    conversions: int = 0
    impressions: int = 0
    clicks: int = 0
    outcome_date: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)

    @property
    def roi(self) -> float:
        return (self.revenue_usd - self.spend_usd) / max(self.spend_usd, 0.01)

    @property
    def ctr(self) -> float:
        return self.clicks / max(self.impressions, 1)

    @property
    def conversion_rate(self) -> float:
        return self.conversions / max(self.clicks, 1)

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "name": self.name,
            "channel": self.channel,
            "spend_usd": self.spend_usd,
            "revenue_usd": self.revenue_usd,
            "conversions": self.conversions,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "outcome_date": self.outcome_date,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CampaignOutcome:
        return cls(
            campaign_id=d.get("campaign_id", str(uuid.uuid4())),
            name=d.get("name", ""),
            channel=d.get("channel", ""),
            spend_usd=d.get("spend_usd", 0.0),
            revenue_usd=d.get("revenue_usd", 0.0),
            conversions=d.get("conversions", 0),
            impressions=d.get("impressions", 0),
            clicks=d.get("clicks", 0),
            outcome_date=d.get("outcome_date", time.time()),
            tags=d.get("tags", []),
        )


@dataclass
class ChannelInsight:
    channel: str
    avg_roi: float = 0.0
    avg_ctr: float = 0.0
    avg_conversion_rate: float = 0.0
    total_campaigns: int = 0
    total_revenue_usd: float = 0.0
    trend: str = "stable"  # improving | stable | declining
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "avg_roi": self.avg_roi,
            "avg_ctr": self.avg_ctr,
            "avg_conversion_rate": self.avg_conversion_rate,
            "total_campaigns": self.total_campaigns,
            "total_revenue_usd": self.total_revenue_usd,
            "trend": self.trend,
            "recommendation": self.recommendation,
        }


class EconomicLearner:
    def __init__(self) -> None:
        self._outcomes: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._outcomes = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._outcomes, ttl_seconds=_CACHE_TTL)
        except Exception:
            pass

    async def record_outcome(self, outcome: CampaignOutcome) -> None:
        await self._load()
        self._outcomes.append(outcome.to_dict())
        await self._save()

    async def analyze_channels(self) -> list[ChannelInsight]:
        await self._load()
        if not self._outcomes:
            return []

        outcomes = [CampaignOutcome.from_dict(d) for d in self._outcomes]

        # Group by channel
        by_channel: dict[str, list[CampaignOutcome]] = {}
        for o in outcomes:
            by_channel.setdefault(o.channel, []).append(o)

        insights: list[ChannelInsight] = []
        for channel, channel_outcomes in by_channel.items():
            n = len(channel_outcomes)
            avg_roi = sum(o.roi for o in channel_outcomes) / n
            avg_ctr = sum(o.ctr for o in channel_outcomes) / n
            avg_cvr = sum(o.conversion_rate for o in channel_outcomes) / n
            total_revenue = sum(o.revenue_usd for o in channel_outcomes)

            # Trend: compare recent 30% vs earlier 70%
            split = max(1, int(n * 0.7))
            early = channel_outcomes[:split]
            recent = channel_outcomes[split:]
            if recent and early:
                early_roi = sum(o.roi for o in early) / len(early)
                recent_roi = sum(o.roi for o in recent) / len(recent)
                if recent_roi > early_roi * 1.1:
                    trend = "improving"
                elif recent_roi < early_roi * 0.9:
                    trend = "declining"
                else:
                    trend = "stable"
            else:
                trend = "stable"

            # Recommendation
            if trend == "improving":
                recommendation = f"Scale spend on {channel} — ROI trending up ({avg_roi:.2f}x avg)."
            elif trend == "declining":
                recommendation = f"Reduce spend on {channel} — ROI declining. Test new creatives or pause."
            else:
                recommendation = f"{channel} is stable at {avg_roi:.2f}x ROI. Optimize targeting to improve."

            insights.append(ChannelInsight(
                channel=channel,
                avg_roi=round(avg_roi, 4),
                avg_ctr=round(avg_ctr, 4),
                avg_conversion_rate=round(avg_cvr, 4),
                total_campaigns=n,
                total_revenue_usd=round(total_revenue, 2),
                trend=trend,
                recommendation=recommendation,
            ))

        return sorted(insights, key=lambda i: i.avg_roi, reverse=True)

    async def best_channels(self, top_k: int = 3) -> list[str]:
        insights = await self.analyze_channels()
        return [i.channel for i in insights[:top_k]]

    async def predict_roi(self, channel: str, spend_usd: float) -> dict:
        await self._load()
        channel_outcomes = [
            CampaignOutcome.from_dict(d)
            for d in self._outcomes
            if d.get("channel") == channel
        ]

        if not channel_outcomes:
            return {
                "channel": channel,
                "spend_usd": spend_usd,
                "predicted_revenue_usd": spend_usd * 1.5,
                "predicted_roi": 0.5,
                "confidence": 0.1,
                "based_on_campaigns": 0,
            }

        n = len(channel_outcomes)
        avg_roi = sum(o.roi for o in channel_outcomes) / n
        # Confidence grows with number of campaigns, capped at 0.95
        confidence = min(0.95, 0.3 + (n / 20) * 0.65)
        predicted_revenue = spend_usd * (1 + avg_roi)

        return {
            "channel": channel,
            "spend_usd": spend_usd,
            "predicted_revenue_usd": round(predicted_revenue, 2),
            "predicted_roi": round(avg_roi, 4),
            "confidence": round(confidence, 4),
            "based_on_campaigns": n,
        }

    async def learning_report(self) -> dict:
        await self._load()
        if not self._outcomes:
            return {
                "total_campaigns": 0,
                "total_spend_usd": 0.0,
                "total_revenue_usd": 0.0,
                "avg_roi": 0.0,
                "best_channel": "",
                "channel_insights": [],
            }

        outcomes = [CampaignOutcome.from_dict(d) for d in self._outcomes]
        total_spend = sum(o.spend_usd for o in outcomes)
        total_revenue = sum(o.revenue_usd for o in outcomes)
        avg_roi = sum(o.roi for o in outcomes) / len(outcomes)

        insights = await self.analyze_channels()
        best_channel = insights[0].channel if insights else ""

        return {
            "total_campaigns": len(outcomes),
            "total_spend_usd": round(total_spend, 2),
            "total_revenue_usd": round(total_revenue, 2),
            "avg_roi": round(avg_roi, 4),
            "best_channel": best_channel,
            "channel_insights": [i.to_dict() for i in insights],
        }

    def summary(self) -> dict:
        if not self._outcomes:
            return {"total_outcomes": 0, "avg_roi": 0.0}
        outcomes = [CampaignOutcome.from_dict(d) for d in self._outcomes]
        avg_roi = sum(o.roi for o in outcomes) / len(outcomes)
        return {
            "total_outcomes": len(outcomes),
            "avg_roi": round(avg_roi, 4),
        }


_learner_instance: Optional[EconomicLearner] = None


def get_economic_learner() -> EconomicLearner:
    global _learner_instance
    if _learner_instance is None:
        _learner_instance = EconomicLearner()
    return _learner_instance
