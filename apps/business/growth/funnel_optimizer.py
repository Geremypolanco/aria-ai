"""
Funnel Analysis and Conversion Optimization — Phase 5
Tracks user journey events, identifies drop points, and recommends improvements.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from apps.core.memory.redis_client import get_cache

logger = logging.getLogger(__name__)

_EVENTS_KEY = "funnel:events:v1"
_EVENTS_TTL = 86400 * 30  # 30 days
_MAX_EVENTS = 10_000


class FunnelStage(StrEnum):
    AWARENESS = "awareness"
    INTEREST = "interest"
    CONSIDERATION = "consideration"
    INTENT = "intent"
    CONVERSION = "conversion"
    RETENTION = "retention"


# Ordered stage progression for drop-rate calculations
_STAGE_ORDER = [
    FunnelStage.AWARENESS,
    FunnelStage.INTEREST,
    FunnelStage.CONSIDERATION,
    FunnelStage.INTENT,
    FunnelStage.CONVERSION,
    FunnelStage.RETENTION,
]


@dataclass
class FunnelEvent:
    event_id: str
    session_id: str
    stage: FunnelStage
    action: str
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stage"] = self.stage.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FunnelEvent:
        d = dict(d)
        d["stage"] = FunnelStage(d["stage"])
        return cls(**d)


@dataclass
class FunnelMetrics:
    stage: FunnelStage
    entries: int
    exits: int
    conversions_to_next: int

    @property
    def conversion_rate(self) -> float:
        if self.entries == 0:
            return 0.0
        return self.conversions_to_next / self.entries

    @property
    def drop_rate(self) -> float:
        if self.entries == 0:
            return 0.0
        return self.exits / self.entries


@dataclass
class ConversionOpportunity:
    stage: FunnelStage
    issue: str
    impact_score: float
    recommended_action: str


# ------------------------------------------------------------------
# A/B test recommendations per stage (deterministic, no LLM)
# ------------------------------------------------------------------
_AB_RECOMMENDATIONS: dict[FunnelStage, str] = {
    FunnelStage.AWARENESS: (
        "Test headline copy variants: value-led ('Save 3 hours/day') vs. "
        "problem-led ('Tired of manual work?'). Measure CTR over 1,000 impressions."
    ),
    FunnelStage.INTEREST: (
        "Test social proof placement: reviews above-the-fold vs. below the hero. "
        "Measure scroll depth and time-on-page."
    ),
    FunnelStage.CONSIDERATION: (
        "Test pricing display: monthly price vs. annual-per-month breakdown. "
        "Measure feature-comparison page engagement."
    ),
    FunnelStage.INTENT: (
        "Test CTA button color (primary brand vs. high-contrast orange) and copy "
        "('Start Free Trial' vs. 'Get Instant Access'). Measure click-through rate."
    ),
    FunnelStage.CONVERSION: (
        "Test checkout flow: single-page vs. multi-step. Reduce required fields. "
        "Measure cart abandonment and completion rate."
    ),
    FunnelStage.RETENTION: (
        "Test onboarding email cadence: day 1/3/7 sequence vs. day 1/2/5/14. "
        "Measure 30-day retention and feature adoption rate."
    ),
}

_OPPORTUNITY_RULES: dict[FunnelStage, dict[str, Any]] = {
    FunnelStage.AWARENESS: {
        "issue": "High impressions but low click-through rate",
        "recommended_action": "Refresh ad creative and headline copy; add urgency cues",
    },
    FunnelStage.INTEREST: {
        "issue": "Visitors not engaging with product features",
        "recommended_action": "Add interactive demo or video walkthrough above fold",
    },
    FunnelStage.CONSIDERATION: {
        "issue": "Users comparing but not advancing to purchase intent",
        "recommended_action": "Introduce risk-reversal (money-back guarantee, free trial)",
    },
    FunnelStage.INTENT: {
        "issue": "High intent but abandonment before checkout",
        "recommended_action": "Add exit-intent popup with limited-time discount",
    },
    FunnelStage.CONVERSION: {
        "issue": "Cart abandonment at payment step",
        "recommended_action": "Simplify checkout, add trust badges and payment logos",
    },
    FunnelStage.RETENTION: {
        "issue": "Low repeat engagement after first purchase",
        "recommended_action": "Launch win-back sequence with personalized content at day 7 and 14",
    },
}


class FunnelOptimizer:
    """Tracks funnel events and generates conversion improvement opportunities."""

    def __init__(self) -> None:
        self._events: list[FunnelEvent] = []
        self._loaded = False

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_EVENTS_KEY)
            if data and isinstance(data, list):
                for item in data:
                    try:
                        self._events.append(FunnelEvent.from_dict(item))
                    except Exception:
                        logger.warning("Skipping malformed funnel event")
        except Exception:
            logger.exception("FunnelOptimizer._load failed")
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            # Keep last _MAX_EVENTS events
            trimmed = self._events[-_MAX_EVENTS:]
            payload = [ev.to_dict() for ev in trimmed]
            await cache.set(_EVENTS_KEY, payload, ttl_seconds=_EVENTS_TTL)
        except Exception:
            logger.exception("FunnelOptimizer._save failed")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def track_event(
        self,
        session_id: str,
        stage: FunnelStage,
        action: str,
        metadata: dict[str, Any] | None = None,
    ) -> FunnelEvent:
        """Log a funnel event for the given session."""
        await self._load()
        event = FunnelEvent(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            stage=stage,
            action=action,
            timestamp=time.time(),
            metadata=metadata or {},
        )
        self._events.append(event)
        # Trim in-memory list to cap
        if len(self._events) > _MAX_EVENTS:
            self._events = self._events[-_MAX_EVENTS:]
        await self._save()
        return event

    async def get_funnel_metrics(self) -> list[FunnelMetrics]:
        """Compute entry/exit/conversion metrics per funnel stage."""
        await self._load()

        # Count unique sessions per stage
        stage_sessions: dict[FunnelStage, set[str]] = {s: set() for s in _STAGE_ORDER}
        for ev in self._events:
            stage_sessions[ev.stage].add(ev.session_id)

        metrics: list[FunnelMetrics] = []
        for i, stage in enumerate(_STAGE_ORDER):
            sessions_here = len(stage_sessions[stage])
            if i + 1 < len(_STAGE_ORDER):
                next_stage = _STAGE_ORDER[i + 1]
                progressed = len(stage_sessions[stage] & stage_sessions[next_stage])
            else:
                progressed = 0

            exits = max(0, sessions_here - progressed)
            metrics.append(
                FunnelMetrics(
                    stage=stage,
                    entries=sessions_here,
                    exits=exits,
                    conversions_to_next=progressed,
                )
            )
        return metrics

    async def identify_drop_points(self) -> list[FunnelStage]:
        """Return stages where drop_rate exceeds 50%."""
        metrics = await self.get_funnel_metrics()
        return [m.stage for m in metrics if m.drop_rate > 0.5]

    async def generate_opportunities(self) -> list[ConversionOpportunity]:
        """Return ranked ConversionOpportunity list for high-drop stages."""
        drop_stages = await self.identify_drop_points()
        metrics = await self.get_funnel_metrics()
        metrics_by_stage = {m.stage: m for m in metrics}

        opportunities: list[ConversionOpportunity] = []
        for stage in drop_stages:
            rule = _OPPORTUNITY_RULES.get(stage)
            if not rule:
                continue
            m = metrics_by_stage.get(stage)
            # Impact score: higher drop rate = higher impact, weighted by entries
            drop_rate = m.drop_rate if m else 0.5
            entries = m.entries if m else 1
            impact = round(drop_rate * min(entries / 10, 10), 2)
            opportunities.append(
                ConversionOpportunity(
                    stage=stage,
                    issue=rule["issue"],
                    impact_score=impact,
                    recommended_action=rule["recommended_action"],
                )
            )

        opportunities.sort(key=lambda o: o.impact_score, reverse=True)
        return opportunities

    async def ab_test_recommendation(self, stage: FunnelStage) -> str:
        """Return a deterministic A/B test recommendation for the given stage."""
        return _AB_RECOMMENDATIONS.get(
            stage,
            f"Test the primary CTA copy and placement at the {stage.value} stage.",
        )

    def summary(self) -> dict[str, Any]:
        """Synchronous high-level summary (uses cached event state)."""
        if not self._events:
            return {
                "overall_conversion_rate": 0.0,
                "bottleneck_stage": None,
                "top_opportunity": None,
                "total_events": 0,
            }

        stage_sessions: dict[FunnelStage, set[str]] = {s: set() for s in _STAGE_ORDER}
        for ev in self._events:
            stage_sessions[ev.stage].add(ev.session_id)

        awareness_count = len(stage_sessions[FunnelStage.AWARENESS])
        conversion_count = len(stage_sessions[FunnelStage.CONVERSION])
        overall_cr = conversion_count / awareness_count if awareness_count > 0 else 0.0

        # Bottleneck: stage with most exits
        bottleneck: FunnelStage | None = None
        max_exits = -1
        for i, stage in enumerate(_STAGE_ORDER[:-1]):
            next_stage = _STAGE_ORDER[i + 1]
            here = len(stage_sessions[stage])
            progressed = len(stage_sessions[stage] & stage_sessions[next_stage])
            exits = here - progressed
            if exits > max_exits:
                max_exits = exits
                bottleneck = stage

        return {
            "overall_conversion_rate": overall_cr,
            "bottleneck_stage": bottleneck.value if bottleneck else None,
            "top_opportunity": (
                _OPPORTUNITY_RULES.get(bottleneck, {}).get("recommended_action")
                if bottleneck
                else None
            ),
            "total_events": len(self._events),
        }


# ------------------------------------------------------------------
# Singleton factory
# ------------------------------------------------------------------

_funnel_optimizer_instance: FunnelOptimizer | None = None


def get_funnel_optimizer() -> FunnelOptimizer:
    global _funnel_optimizer_instance
    if _funnel_optimizer_instance is None:
        _funnel_optimizer_instance = FunnelOptimizer()
    return _funnel_optimizer_instance
