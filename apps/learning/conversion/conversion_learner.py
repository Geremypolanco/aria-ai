from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache

_CACHE_KEY = "learning:conversion:v1"
_CACHE_TTL = 86400 * 365  # 365 days


@dataclass
class ConversionEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    stage: str = ""
    converted: bool = False
    time_to_convert_seconds: float = 0.0
    channel: str = ""
    device: str = ""
    value_usd: float = 0.0
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "stage": self.stage,
            "converted": self.converted,
            "time_to_convert_seconds": self.time_to_convert_seconds,
            "channel": self.channel,
            "device": self.device,
            "value_usd": self.value_usd,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ConversionEvent:
        return cls(
            event_id=d.get("event_id", str(uuid.uuid4())),
            session_id=d.get("session_id", ""),
            stage=d.get("stage", ""),
            converted=d.get("converted", False),
            time_to_convert_seconds=d.get("time_to_convert_seconds", 0.0),
            channel=d.get("channel", ""),
            device=d.get("device", ""),
            value_usd=d.get("value_usd", 0.0),
            timestamp=d.get("timestamp", time.time()),
            metadata=d.get("metadata", {}),
        )


@dataclass
class FunnelInsight:
    stage: str
    conversion_rate: float = 0.0
    avg_time_seconds: float = 0.0
    drop_rate: float = 0.0
    optimization_tip: str = ""
    revenue_impact_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "conversion_rate": self.conversion_rate,
            "avg_time_seconds": self.avg_time_seconds,
            "drop_rate": self.drop_rate,
            "optimization_tip": self.optimization_tip,
            "revenue_impact_usd": self.revenue_impact_usd,
        }


class ConversionLearner:
    def __init__(self) -> None:
        self._events: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._events = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._events, ttl_seconds=_CACHE_TTL)
        except Exception:
            pass

    async def record(self, event: ConversionEvent) -> None:
        await self._load()
        self._events.append(event.to_dict())
        await self._save()

    async def funnel_analysis(self) -> list[FunnelInsight]:
        await self._load()
        if not self._events:
            return []

        events = [ConversionEvent.from_dict(d) for d in self._events]

        # Group by stage
        by_stage: dict[str, list[ConversionEvent]] = {}
        for e in events:
            by_stage.setdefault(e.stage, []).append(e)

        total_revenue = sum(e.value_usd for e in events if e.converted)
        insights: list[FunnelInsight] = []

        for stage, stage_events in by_stage.items():
            n = len(stage_events)
            converted = [e for e in stage_events if e.converted]
            cvr = len(converted) / n if n > 0 else 0.0
            drop_rate = 1.0 - cvr
            avg_time = (
                sum(e.time_to_convert_seconds for e in converted) / len(converted)
                if converted else 0.0
            )
            stage_revenue = sum(e.value_usd for e in converted)

            # Generate optimization tip based on performance
            if cvr < 0.05:
                tip = f"Critical: {stage} converts at only {cvr:.1%}. A/B test messaging and reduce friction immediately."
            elif cvr < 0.15:
                tip = f"{stage} is underperforming ({cvr:.1%} CVR). Add social proof and simplify the path to action."
            elif drop_rate > 0.6:
                tip = f"High drop-off at {stage} ({drop_rate:.1%}). Investigate exit intent and add re-engagement triggers."
            else:
                tip = f"{stage} performing well ({cvr:.1%} CVR). Scale traffic to this stage."

            insights.append(FunnelInsight(
                stage=stage,
                conversion_rate=round(cvr, 4),
                avg_time_seconds=round(avg_time, 2),
                drop_rate=round(drop_rate, 4),
                optimization_tip=tip,
                revenue_impact_usd=round(stage_revenue, 2),
            ))

        return sorted(insights, key=lambda i: i.conversion_rate, reverse=True)

    async def identify_friction_points(self) -> list[dict]:
        insights = await self.funnel_analysis()
        friction = []
        for i, insight in enumerate(insights):
            if insight.conversion_rate < 0.1 or insight.drop_rate > 0.5:
                if insight.conversion_rate < 0.05:
                    priority = "critical"
                    fix = "Redesign this stage — remove fields, add trust signals, simplify CTA"
                elif insight.drop_rate > 0.7:
                    priority = "high"
                    fix = "Add exit-intent popup, improve loading speed, and clarify value proposition"
                else:
                    priority = "medium"
                    fix = "A/B test copy changes, improve mobile UX, add progress indicators"

                friction.append({
                    "stage": insight.stage,
                    "conversion_rate": insight.conversion_rate,
                    "drop_rate": insight.drop_rate,
                    "priority": priority,
                    "recommended_fix": fix,
                })

        return sorted(friction, key=lambda f: f["drop_rate"], reverse=True)

    async def optimal_flow(self) -> list[str]:
        insights = await self.funnel_analysis()
        # Sorted by CVR desc already — fastest path to conversion
        return [i.stage for i in insights]

    async def conversion_forecast(
        self, target_conversions: int, current_cvr: float = 0.02
    ) -> dict:
        await self._load()

        # Use actual CVR if we have data
        if self._events:
            events = [ConversionEvent.from_dict(d) for d in self._events]
            converted = [e for e in events if e.converted]
            actual_cvr = len(converted) / len(events) if events else current_cvr
        else:
            actual_cvr = current_cvr

        cvr = max(actual_cvr, 0.001)
        required_visitors = int(target_conversions / cvr)
        # Assume $1 CPC and 30-day window
        required_spend = required_visitors * 1.0
        # Assume 1000 organic visitors/day baseline
        daily_visitors = 1000
        time_to_target = max(1, int(required_visitors / daily_visitors))

        # Recommend focus
        friction = await self.identify_friction_points()
        if friction:
            recommended_focus = f"Fix friction at '{friction[0]['stage']}' stage first — {friction[0]['recommended_fix']}"
        else:
            recommended_focus = "Increase top-of-funnel traffic and optimize landing page messaging"

        return {
            "required_visitors": required_visitors,
            "required_spend_usd": round(required_spend, 2),
            "time_to_target_days": time_to_target,
            "recommended_focus": recommended_focus,
        }

    def summary(self) -> dict:
        if not self._events:
            return {"total_events": 0, "overall_conversion_rate": 0.0, "top_channel": ""}

        events = [ConversionEvent.from_dict(d) for d in self._events]
        converted = [e for e in events if e.converted]
        overall_cvr = len(converted) / len(events)

        # Top channel by conversion count
        channel_counts: dict[str, int] = {}
        for e in converted:
            if e.channel:
                channel_counts[e.channel] = channel_counts.get(e.channel, 0) + 1
        top_channel = max(channel_counts, key=lambda c: channel_counts[c]) if channel_counts else ""

        return {
            "total_events": len(events),
            "overall_conversion_rate": round(overall_cvr, 4),
            "top_channel": top_channel,
        }


_learner_instance: Optional[ConversionLearner] = None


def get_conversion_learner() -> ConversionLearner:
    global _learner_instance
    if _learner_instance is None:
        _learner_instance = ConversionLearner()
    return _learner_instance
