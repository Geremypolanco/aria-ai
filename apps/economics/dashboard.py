"""
EconomicDashboard — Real business metrics tracking.

Tracks:
  CTR  — Click-Through Rate (clicks / impressions)
  CAC  — Customer Acquisition Cost (ad_spend / new_customers)
  LTV  — Lifetime Value per customer
  ROAS — Return on Ad Spend (revenue / ad_spend)

Events are recorded via track_event() and aggregated on demand.
Provides daily/weekly/monthly breakdowns.
"""
from __future__ import annotations

import datetime
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.economics.dashboard")

_EVENTS_KEY = "economics:events:v1"
_SNAPSHOTS_KEY = "economics:snapshots:v1"
_EVENTS_TTL = 86400 * 90       # 90 days
_SNAPSHOTS_TTL = 86400 * 365   # 365 days

_VALID_EVENT_TYPES = {"impression", "click", "lead", "purchase", "spend"}


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class MetricEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    event_type: str = ""
    channel: str = ""
    amount: float = 0.0
    metadata: dict = field(default_factory=dict)
    recorded_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "channel": self.channel,
            "amount": round(self.amount, 4),
            "metadata": self.metadata,
            "recorded_at": self.recorded_at,
        }


@dataclass
class ChannelMetrics:
    channel: str = ""
    impressions: int = 0
    clicks: int = 0
    leads: int = 0
    purchases: int = 0
    spend_usd: float = 0.0
    revenue_usd: float = 0.0

    @property
    def ctr_pct(self) -> float:
        if self.impressions == 0:
            return 0.0
        return round(self.clicks / self.impressions * 100, 4)

    @property
    def cac_usd(self) -> float:
        if self.purchases == 0:
            return 0.0
        return round(self.spend_usd / self.purchases, 4)

    @property
    def ltv_usd(self) -> float:
        if self.purchases == 0:
            return 0.0
        return round(self.revenue_usd / self.purchases, 4)

    @property
    def roas(self) -> float:
        if self.spend_usd == 0:
            return 0.0
        return round(self.revenue_usd / self.spend_usd, 4)

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "leads": self.leads,
            "purchases": self.purchases,
            "spend_usd": round(self.spend_usd, 4),
            "revenue_usd": round(self.revenue_usd, 4),
            "ctr_pct": self.ctr_pct,
            "cac_usd": self.cac_usd,
            "ltv_usd": self.ltv_usd,
            "roas": self.roas,
        }


@dataclass
class DashboardSnapshot:
    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    period: str = "daily"
    date: str = ""
    total_impressions: int = 0
    total_clicks: int = 0
    total_leads: int = 0
    total_purchases: int = 0
    total_spend_usd: float = 0.0
    total_revenue_usd: float = 0.0
    ctr_pct: float = 0.0
    cac_usd: float = 0.0
    ltv_usd: float = 0.0
    roas: float = 0.0
    top_channel: str = ""
    channels: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "period": self.period,
            "date": self.date,
            "total_impressions": self.total_impressions,
            "total_clicks": self.total_clicks,
            "total_leads": self.total_leads,
            "total_purchases": self.total_purchases,
            "total_spend_usd": round(self.total_spend_usd, 4),
            "total_revenue_usd": round(self.total_revenue_usd, 4),
            "ctr_pct": round(self.ctr_pct, 4),
            "cac_usd": round(self.cac_usd, 4),
            "ltv_usd": round(self.ltv_usd, 4),
            "roas": round(self.roas, 4),
            "top_channel": self.top_channel,
            "channels": self.channels,
            "created_at": self.created_at,
        }


# ── Main class ────────────────────────────────────────────────────────────────

class EconomicDashboard:
    """Real business metrics tracking for ARIA AI."""

    def __init__(self) -> None:
        self._events: list[dict] = []
        self._snapshots: list[dict] = []
        self._loaded: bool = False

    # ── Persistence ──────────────────────────────────────────────────────────

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            events_data = await cache.get(_EVENTS_KEY)
            snapshots_data = await cache.get(_SNAPSHOTS_KEY)
            if isinstance(events_data, list):
                self._events = events_data
            if isinstance(snapshots_data, list):
                self._snapshots = snapshots_data
        except Exception as exc:
            logger.warning("EconomicDashboard._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            # Keep last 10000 events and last 365 snapshots
            trimmed_events = self._events[-10000:]
            trimmed_snapshots = self._snapshots[-365:]
            await cache.set(_EVENTS_KEY, trimmed_events, ttl_seconds=_EVENTS_TTL)
            await cache.set(_SNAPSHOTS_KEY, trimmed_snapshots, ttl_seconds=_SNAPSHOTS_TTL)
            self._events = trimmed_events
            self._snapshots = trimmed_snapshots
        except Exception as exc:
            logger.warning("EconomicDashboard._save failed: %s", exc)

    # ── Event Tracking ───────────────────────────────────────────────────────

    async def track_event(
        self,
        event_type: str,
        channel: str,
        amount: float = 0.0,
        metadata: dict = {},
    ) -> MetricEvent:
        """Record a single metric event and persist to Redis."""
        await self._load()

        if event_type not in _VALID_EVENT_TYPES:
            logger.warning("Unknown event_type '%s', defaulting to 'impression'", event_type)
            event_type = "impression"

        event = MetricEvent(
            event_type=event_type,
            channel=channel.strip().lower() or "unknown",
            amount=max(0.0, amount),
            metadata=dict(metadata),
        )
        self._events.append(event.to_dict())
        await self._save()
        return event

    # ── Aggregation ──────────────────────────────────────────────────────────

    def get_channel_metrics(self, channel: str = "", since_ts: float = 0.0) -> ChannelMetrics:
        """Aggregate events for a specific channel (or all if channel='') since since_ts."""
        ch_lower = channel.strip().lower()
        metrics = ChannelMetrics(channel=ch_lower or "all")

        for ev in self._events:
            if since_ts > 0 and ev.get("recorded_at", 0) < since_ts:
                continue
            if ch_lower and ev.get("channel", "") != ch_lower:
                continue

            etype = ev.get("event_type", "")
            amount = ev.get("amount", 0.0)

            if etype == "impression":
                metrics.impressions += 1
            elif etype == "click":
                metrics.clicks += 1
            elif etype == "lead":
                metrics.leads += 1
            elif etype == "purchase":
                metrics.purchases += 1
                metrics.revenue_usd += amount
            elif etype == "spend":
                metrics.spend_usd += amount

        return metrics

    def get_all_channel_metrics(self, since_ts: float = 0.0) -> list[ChannelMetrics]:
        """Return per-channel metrics sorted by revenue_usd descending."""
        seen_channels: set[str] = set()
        for ev in self._events:
            if since_ts > 0 and ev.get("recorded_at", 0) < since_ts:
                continue
            ch = ev.get("channel", "unknown")
            if ch:
                seen_channels.add(ch)

        results = []
        for ch in seen_channels:
            results.append(self.get_channel_metrics(channel=ch, since_ts=since_ts))

        results.sort(key=lambda m: m.revenue_usd, reverse=True)
        return results

    # ── Snapshots ────────────────────────────────────────────────────────────

    async def snapshot_today(self) -> DashboardSnapshot:
        """Aggregate today's events and save a DashboardSnapshot."""
        await self._load()

        today = datetime.date.today()
        today_str = today.isoformat()
        since_ts = datetime.datetime.combine(today, datetime.time.min).timestamp()

        all_channels = self.get_all_channel_metrics(since_ts=since_ts)

        total_impressions = sum(c.impressions for c in all_channels)
        total_clicks = sum(c.clicks for c in all_channels)
        total_leads = sum(c.leads for c in all_channels)
        total_purchases = sum(c.purchases for c in all_channels)
        total_spend = sum(c.spend_usd for c in all_channels)
        total_revenue = sum(c.revenue_usd for c in all_channels)

        ctr_pct = (total_clicks / total_impressions * 100) if total_impressions else 0.0
        cac_usd = (total_spend / total_purchases) if total_purchases else 0.0
        ltv_usd = (total_revenue / total_purchases) if total_purchases else 0.0
        roas = (total_revenue / total_spend) if total_spend else 0.0

        # top_channel: most revenue; fallback to most clicks
        top_channel = ""
        if all_channels:
            by_revenue = [c for c in all_channels if c.revenue_usd > 0]
            if by_revenue:
                top_channel = by_revenue[0].channel
            else:
                by_clicks = sorted(all_channels, key=lambda c: c.clicks, reverse=True)
                if by_clicks and by_clicks[0].clicks > 0:
                    top_channel = by_clicks[0].channel

        snap = DashboardSnapshot(
            period="daily",
            date=today_str,
            total_impressions=total_impressions,
            total_clicks=total_clicks,
            total_leads=total_leads,
            total_purchases=total_purchases,
            total_spend_usd=total_spend,
            total_revenue_usd=total_revenue,
            ctr_pct=round(ctr_pct, 4),
            cac_usd=round(cac_usd, 4),
            ltv_usd=round(ltv_usd, 4),
            roas=round(roas, 4),
            top_channel=top_channel,
            channels=[c.to_dict() for c in all_channels],
        )
        self._snapshots.append(snap.to_dict())
        await self._save()
        return snap

    # ── Summary & Reports ────────────────────────────────────────────────────

    def dashboard_summary(self) -> dict:
        """High-level summary computed from all-time data."""
        all_channels = self.get_all_channel_metrics(since_ts=0.0)

        total_impressions = sum(c.impressions for c in all_channels)
        total_clicks = sum(c.clicks for c in all_channels)
        total_purchases = sum(c.purchases for c in all_channels)
        total_spend = sum(c.spend_usd for c in all_channels)
        total_revenue = sum(c.revenue_usd for c in all_channels)

        ctr_pct = (total_clicks / total_impressions * 100) if total_impressions else 0.0
        cac_usd = (total_spend / total_purchases) if total_purchases else 0.0
        ltv_usd = (total_revenue / total_purchases) if total_purchases else 0.0
        roas = (total_revenue / total_spend) if total_spend else 0.0

        health_score = min(100.0, roas * 20) if roas > 0 else 0.0

        last_snapshot_date = "never"
        if self._snapshots:
            last_snapshot_date = self._snapshots[-1].get("date", "never")

        top_5 = [c.to_dict() for c in all_channels[:5]]

        return {
            "total_events_tracked": len(self._events),
            "snapshots_count": len(self._snapshots),
            "current_metrics": {
                "ctr_pct": round(ctr_pct, 4),
                "cac_usd": round(cac_usd, 4),
                "ltv_usd": round(ltv_usd, 4),
                "roas": round(roas, 4),
            },
            "top_channels": top_5,
            "last_snapshot_date": last_snapshot_date,
            "economic_health_score": round(health_score, 2),
        }

    async def weekly_report(self) -> dict:
        """AI-generated weekly performance analysis."""
        await self._load()

        # Gather metrics for the last 7 days
        seven_days_ago = time.time() - 86400 * 7
        all_channels = self.get_all_channel_metrics(since_ts=seven_days_ago)

        total_spend = sum(c.spend_usd for c in all_channels)
        total_revenue = sum(c.revenue_usd for c in all_channels)
        total_impressions = sum(c.impressions for c in all_channels)
        total_clicks = sum(c.clicks for c in all_channels)
        total_purchases = sum(c.purchases for c in all_channels)

        ctr_pct = (total_clicks / total_impressions * 100) if total_impressions else 0.0
        cac_usd = (total_spend / total_purchases) if total_purchases else 0.0
        roas = (total_revenue / total_spend) if total_spend else 0.0

        summary_dict = {
            "period": "last_7_days",
            "total_revenue_usd": round(total_revenue, 2),
            "total_spend_usd": round(total_spend, 2),
            "roas": round(roas, 4),
            "ctr_pct": round(ctr_pct, 4),
            "cac_usd": round(cac_usd, 4),
            "top_channels": [c.to_dict() for c in all_channels[:3]],
        }

        ai_analysis = "Insufficient data for AI analysis."
        try:
            ai = get_ai_client()
            result = await ai.complete(
                system="You are an economic analyst for ARIA AI, a business automation platform.",
                user=(
                    f"Weekly metrics: {summary_dict}. "
                    "Write a 3-sentence analysis of performance and top recommendation."
                ),
                model=AIModel.FAST,
                max_tokens=200,
            )
            if result.success:
                ai_analysis = result.content.strip()
        except Exception as exc:
            logger.warning("weekly_report AI call failed: %s", exc)

        return {
            "period": "last_7_days",
            "metrics": summary_dict,
            "ai_analysis": ai_analysis,
            "generated_at": time.time(),
        }

    def recent_events(self, limit: int = 50, event_type: str = "") -> list[dict]:
        """Return the most recent N events, optionally filtered by event_type."""
        events = self._events
        if event_type:
            events = [e for e in events if e.get("event_type") == event_type]
        return events[-limit:]


# ── Singleton ─────────────────────────────────────────────────────────────────

_dashboard_instance: EconomicDashboard | None = None


def get_economic_dashboard() -> EconomicDashboard:
    global _dashboard_instance
    if _dashboard_instance is None:
        _dashboard_instance = EconomicDashboard()
    return _dashboard_instance
