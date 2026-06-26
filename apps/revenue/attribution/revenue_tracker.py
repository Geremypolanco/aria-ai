"""
Revenue attribution and conversion tracking across channels.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from apps.core.memory.redis_client import get_cache

_TRACKER_KEY = "revenue:tracker:v1"
_TRACKER_TTL = 86400 * 90


class AttributionModel(StrEnum):
    LAST_TOUCH = "last_touch"
    FIRST_TOUCH = "first_touch"
    LINEAR = "linear"
    TIME_DECAY = "time_decay"


@dataclass
class ConversionEvent:
    event_id: str
    customer_id: str
    channel: str
    amount_usd: float
    timestamp: float
    touchpoints: list[str] = field(default_factory=list)
    product_id: str = ""
    campaign_id: str = ""

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "customer_id": self.customer_id,
            "channel": self.channel,
            "amount_usd": self.amount_usd,
            "timestamp": self.timestamp,
            "touchpoints": self.touchpoints,
            "product_id": self.product_id,
            "campaign_id": self.campaign_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ConversionEvent:
        return cls(**d)


@dataclass
class ChannelAttribution:
    channel: str
    attributed_revenue: float
    conversion_count: int
    avg_order_value: float
    attribution_model: str

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "attributed_revenue": round(self.attributed_revenue, 2),
            "conversion_count": self.conversion_count,
            "avg_order_value": round(self.avg_order_value, 2),
            "attribution_model": self.attribution_model,
        }


class RevenueTracker:
    def __init__(self) -> None:
        self._events: list[dict] = []
        self._loaded = False

    async def _load(self) -> list[dict]:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_TRACKER_KEY)
                if isinstance(data, list):
                    self._events = data
            except Exception:
                pass
            self._loaded = True
        return self._events

    async def _save(self, events: list[dict]) -> None:
        self._events = events[-5000:]  # cap
        try:
            cache = get_cache()
            await cache.set(_TRACKER_KEY, self._events, ttl_seconds=_TRACKER_TTL)
        except Exception:
            pass

    async def record_conversion(
        self,
        customer_id: str,
        channel: str,
        amount_usd: float,
        touchpoints: list[str] | None = None,
        product_id: str = "",
        campaign_id: str = "",
    ) -> ConversionEvent:
        event = ConversionEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            channel=channel,
            amount_usd=amount_usd,
            timestamp=time.time(),
            touchpoints=touchpoints or [channel],
            product_id=product_id,
            campaign_id=campaign_id,
        )
        events = await self._load()
        events.append(event.to_dict())
        await self._save(events)
        return event

    async def roi_by_channel(
        self,
        model: AttributionModel = AttributionModel.LAST_TOUCH,
    ) -> list[ChannelAttribution]:
        events = await self._load()
        by_channel: dict[str, dict] = {}

        for ev_dict in events:
            ev = ConversionEvent.from_dict(ev_dict)
            channel_credits = self._apply_attribution(ev, model)
            for ch, credit in channel_credits.items():
                if ch not in by_channel:
                    by_channel[ch] = {"revenue": 0.0, "count": 0}
                by_channel[ch]["revenue"] += credit
                by_channel[ch]["count"] += 1

        result = []
        for ch, data in by_channel.items():
            count = max(data["count"], 1)
            result.append(
                ChannelAttribution(
                    channel=ch,
                    attributed_revenue=data["revenue"],
                    conversion_count=data["count"],
                    avg_order_value=data["revenue"] / count,
                    attribution_model=model.value,
                )
            )
        result.sort(key=lambda r: r.attributed_revenue, reverse=True)
        return result

    def _apply_attribution(
        self, event: ConversionEvent, model: AttributionModel
    ) -> dict[str, float]:
        touchpoints = event.touchpoints or [event.channel]
        amount = event.amount_usd

        if model == AttributionModel.LAST_TOUCH:
            return {touchpoints[-1]: amount}
        if model == AttributionModel.FIRST_TOUCH:
            return {touchpoints[0]: amount}
        if model == AttributionModel.LINEAR:
            share = amount / len(touchpoints)
            credit: dict[str, float] = {}
            for tp in touchpoints:
                credit[tp] = credit.get(tp, 0.0) + share
            return credit
        # TIME_DECAY: later touchpoints get more credit
        n = len(touchpoints)
        weights = [2**i for i in range(n)]
        total_w = sum(weights)
        credit = {}
        for i, tp in enumerate(touchpoints):
            credit[tp] = credit.get(tp, 0.0) + amount * weights[i] / total_w
        return credit

    async def revenue_forecast(self, months: int = 3) -> list[dict]:
        events = await self._load()
        if not events:
            return [{"month": m + 1, "forecast_usd": 0.0} for m in range(months)]

        now = time.time()
        month_seconds = 30 * 86400
        monthly: dict[int, float] = {}
        for ev in events:
            age_months = int((now - ev["timestamp"]) / month_seconds)
            monthly[age_months] = monthly.get(age_months, 0.0) + ev["amount_usd"]

        recent_months = [monthly.get(i, 0.0) for i in range(min(3, len(monthly)))]
        avg = sum(recent_months) / max(len(recent_months), 1)
        growth = 0.05

        return [
            {"month": m + 1, "forecast_usd": round(avg * ((1 + growth) ** m), 2)}
            for m in range(months)
        ]

    def summary(self) -> dict:
        total = sum(ev["amount_usd"] for ev in self._events)
        return {
            "total_conversions": len(self._events),
            "total_revenue_usd": round(total, 2),
        }


_tracker_instance: RevenueTracker | None = None


def get_revenue_tracker() -> RevenueTracker:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = RevenueTracker()
    return _tracker_instance
