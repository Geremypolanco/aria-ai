"""Phase 14 tests — EconomicDashboard."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="Strong CTR performance this week. LinkedIn driving highest ROAS. Increase LinkedIn spend by 20%."):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


@pytest.fixture
def dashboard():
    with patch("apps.economics.dashboard.get_cache", return_value=_mock_cache()):
        with patch("apps.economics.dashboard.get_ai_client", return_value=_mock_ai()):
            from apps.economics.dashboard import EconomicDashboard
            return EconomicDashboard()


# ── MetricEvent ────────────────────────────────────────────────────────────────

def test_metric_event_to_dict_has_required_keys(dashboard):
    from apps.economics.dashboard import MetricEvent
    e = MetricEvent(event_type="click", channel="twitter", amount=1.0)
    d = e.to_dict()
    required = {"event_id", "event_type", "channel", "amount", "metadata", "recorded_at"}
    assert required.issubset(d.keys())


# ── ChannelMetrics ─────────────────────────────────────────────────────────────

def test_channel_metrics_ctr_zero_on_no_impressions(dashboard):
    from apps.economics.dashboard import ChannelMetrics
    cm = ChannelMetrics(channel="twitter")
    assert cm.ctr_pct == 0.0


def test_channel_metrics_ctr_computed(dashboard):
    from apps.economics.dashboard import ChannelMetrics
    cm = ChannelMetrics(channel="twitter", impressions=1000, clicks=50)
    assert cm.ctr_pct == pytest.approx(5.0)


def test_channel_metrics_cac_zero_on_no_purchases(dashboard):
    from apps.economics.dashboard import ChannelMetrics
    cm = ChannelMetrics(channel="twitter", spend_usd=100.0)
    assert cm.cac_usd == 0.0


def test_channel_metrics_roas_zero_on_no_spend(dashboard):
    from apps.economics.dashboard import ChannelMetrics
    cm = ChannelMetrics(channel="twitter", revenue_usd=500.0)
    assert cm.roas == 0.0


def test_channel_metrics_roas_computed(dashboard):
    from apps.economics.dashboard import ChannelMetrics
    cm = ChannelMetrics(channel="twitter", spend_usd=100.0, revenue_usd=400.0)
    assert cm.roas == pytest.approx(4.0)


def test_channel_metrics_to_dict_has_keys(dashboard):
    from apps.economics.dashboard import ChannelMetrics
    cm = ChannelMetrics(channel="linkedin", impressions=500, clicks=25, spend_usd=50.0, revenue_usd=200.0)
    d = cm.to_dict()
    assert "ctr_pct" in d
    assert "roas" in d
    assert "cac_usd" in d
    assert "ltv_usd" in d


# ── track_event ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_track_event_returns_metric_event(dashboard):
    from apps.economics.dashboard import MetricEvent
    event = await dashboard.track_event("impression", "twitter", 0.0)
    assert isinstance(event, MetricEvent)


@pytest.mark.asyncio
async def test_track_event_stores_in_events(dashboard):
    await dashboard._load()
    await dashboard.track_event("click", "linkedin", 0.0)
    assert len(dashboard._events) == 1


@pytest.mark.asyncio
async def test_track_event_multiple_accumulate(dashboard):
    await dashboard._load()
    await dashboard.track_event("impression", "twitter", 0.0)
    await dashboard.track_event("click", "twitter", 0.0)
    await dashboard.track_event("purchase", "twitter", 50.0)
    assert len(dashboard._events) == 3


@pytest.mark.asyncio
async def test_track_event_event_type_stored(dashboard):
    await dashboard._load()
    event = await dashboard.track_event("lead", "tiktok", 0.0)
    assert event.event_type == "lead"
    assert event.channel == "tiktok"


# ── get_channel_metrics ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_channel_metrics_returns_channel_metrics(dashboard):
    from apps.economics.dashboard import ChannelMetrics
    await dashboard._load()
    await dashboard.track_event("impression", "twitter", 0.0)
    cm = dashboard.get_channel_metrics("twitter")
    assert isinstance(cm, ChannelMetrics)


@pytest.mark.asyncio
async def test_get_channel_metrics_counts_impressions(dashboard):
    await dashboard._load()
    await dashboard.track_event("impression", "twitter", 0.0)
    await dashboard.track_event("impression", "twitter", 0.0)
    cm = dashboard.get_channel_metrics("twitter")
    assert cm.impressions == 2


@pytest.mark.asyncio
async def test_get_channel_metrics_counts_clicks(dashboard):
    await dashboard._load()
    await dashboard.track_event("click", "linkedin", 0.0)
    cm = dashboard.get_channel_metrics("linkedin")
    assert cm.clicks == 1


@pytest.mark.asyncio
async def test_get_channel_metrics_sums_revenue(dashboard):
    await dashboard._load()
    await dashboard.track_event("purchase", "shopify", 99.99)
    await dashboard.track_event("purchase", "shopify", 49.99)
    cm = dashboard.get_channel_metrics("shopify")
    assert cm.revenue_usd == pytest.approx(149.98)


# ── get_all_channel_metrics ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_all_channel_metrics_returns_list(dashboard):
    await dashboard._load()
    await dashboard.track_event("impression", "twitter", 0.0)
    result = dashboard.get_all_channel_metrics()
    assert isinstance(result, list)
    assert len(result) >= 1


@pytest.mark.asyncio
async def test_get_all_channel_metrics_multi_channel(dashboard):
    await dashboard._load()
    for ch in ["twitter", "linkedin", "tiktok"]:
        await dashboard.track_event("impression", ch, 0.0)
    result = dashboard.get_all_channel_metrics()
    channels = {cm.channel for cm in result}
    assert len(channels) == 3


# ── snapshot_today ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_snapshot_today_returns_snapshot(dashboard):
    from apps.economics.dashboard import DashboardSnapshot
    await dashboard._load()
    snap = await dashboard.snapshot_today()
    assert isinstance(snap, DashboardSnapshot)


@pytest.mark.asyncio
async def test_snapshot_today_has_date(dashboard):
    await dashboard._load()
    snap = await dashboard.snapshot_today()
    assert len(snap.date) == 10
    assert "-" in snap.date


@pytest.mark.asyncio
async def test_snapshot_today_has_period(dashboard):
    await dashboard._load()
    snap = await dashboard.snapshot_today()
    assert snap.period in ("daily", "today")


@pytest.mark.asyncio
async def test_snapshot_today_to_dict_has_required_keys(dashboard):
    await dashboard._load()
    snap = await dashboard.snapshot_today()
    d = snap.to_dict()
    required = {"snapshot_id", "period", "date", "total_impressions", "total_clicks",
                "ctr_pct", "roas", "top_channel"}
    assert required.issubset(d.keys())


# ── dashboard_summary ──────────────────────────────────────────────────────────

def test_dashboard_summary_has_required_keys(dashboard):
    summary = dashboard.dashboard_summary()
    required = {"total_events_tracked", "snapshots_count", "current_metrics",
                "top_channels", "last_snapshot_date", "economic_health_score"}
    assert required.issubset(summary.keys())


def test_dashboard_summary_health_score_range(dashboard):
    summary = dashboard.dashboard_summary()
    assert 0 <= summary["economic_health_score"] <= 100


def test_dashboard_summary_top_channels_list(dashboard):
    summary = dashboard.dashboard_summary()
    assert isinstance(summary["top_channels"], list)


# ── weekly_report ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_weekly_report_returns_dict(dashboard):
    await dashboard._load()
    report = await dashboard.weekly_report()
    assert isinstance(report, dict)


@pytest.mark.asyncio
async def test_weekly_report_has_required_keys(dashboard):
    await dashboard._load()
    report = await dashboard.weekly_report()
    assert "period" in report
    assert "metrics" in report
    assert "generated_at" in report


@pytest.mark.asyncio
async def test_weekly_report_has_ai_analysis(dashboard):
    await dashboard._load()
    report = await dashboard.weekly_report()
    assert "ai_analysis" in report
    assert len(report["ai_analysis"]) > 0


# ── recent_events ──────────────────────────────────────────────────────────────

def test_recent_events_returns_list(dashboard):
    result = dashboard.recent_events(limit=10)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_recent_events_after_tracking(dashboard):
    await dashboard._load()
    await dashboard.track_event("impression", "twitter", 0.0)
    result = dashboard.recent_events(limit=10)
    assert len(result) >= 1


@pytest.mark.asyncio
async def test_recent_events_filter_by_type(dashboard):
    await dashboard._load()
    await dashboard.track_event("click", "twitter", 0.0)
    await dashboard.track_event("impression", "linkedin", 0.0)
    clicks = dashboard.recent_events(event_type="click")
    assert all(e["event_type"] == "click" for e in clicks)
