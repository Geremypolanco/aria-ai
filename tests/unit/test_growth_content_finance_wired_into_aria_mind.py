"""Regression test: six complete, honest, previously-unwired engines found by
a reconciliation scout that cross-referenced this session's earlier full-repo
audit (which fixed/deleted fabrication patterns across the whole tree but
did not wire every remaining honest module into the chat dispatcher) against
live callers today.

- LinkingOptimizer (apps/content/internal_linking/linking_optimizer.py):
  internal-link audits/suggestions, no duplicate anywhere.
- EngagementPredictor (apps/content/scoring/engagement_predictor.py) +
  ViralityEngine (apps/content/virality/virality_engine.py): deterministic
  heuristic scoring, disclosed as estimates (confidence/probability fields),
  not fabricated "real" analytics.
- ReinforcementOptimizer (apps/learning/optimization/reinforcement_optimizer.py):
  a genuine UCB1 multi-armed bandit over real recorded rewards.
- ROITracker (apps/economics/roi_tracker.py): pure arithmetic over
  user-supplied investment/returns numbers — picked over the other 8
  ROI/economics modules in the repo as the one canonical, most-honest home
  for this concept (none of the others are wired).
- CashflowEngine (apps/business/finance/cashflow_engine.py): pure bookkeeping
  over user-logged entries, no AI, no randomness, the most conservative
  module wired this session.

Wired into aria_mind.py's tool dispatcher as: audit_internal_links,
suggest_internal_links, generate_pillar_strategy, internal_linking_stats,
predict_engagement, analyze_virality, optimize_viral_title,
select_growth_action, record_action_outcome, reinforcement_report,
track_roi, update_roi_returns, roi_summary, record_cashflow_entry,
cashflow_summary, forecast_cashflow.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engines directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.business.finance.cashflow_engine import CashflowEngine
from apps.content.internal_linking.linking_optimizer import LinkingOptimizer
from apps.core.cognition.aria_mind import AriaMind
from apps.economics.roi_tracker import ROITracker
from apps.learning.optimization.reinforcement_optimizer import ReinforcementOptimizer

pytestmark = pytest.mark.asyncio

OWNER_EMAIL = "owner@aria.test"


class _FakeCache:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value
        return True


@pytest.fixture(autouse=True)
def _patch_caches():
    with (
        patch(
            "apps.content.internal_linking.linking_optimizer.get_cache", return_value=_FakeCache()
        ),
        patch(
            "apps.learning.optimization.reinforcement_optimizer.get_cache",
            return_value=_FakeCache(),
        ),
        patch("apps.economics.roi_tracker.get_cache", return_value=_FakeCache()),
        patch("apps.business.finance.cashflow_engine.get_cache", return_value=_FakeCache()),
        patch("apps.core.auth.is_owner_email", side_effect=lambda e: e == OWNER_EMAIL),
    ):
        yield


# ── LinkingOptimizer ──────────────────────────────────────────────────
async def test_audit_internal_links_reachable_from_tool_dispatch():
    engine = LinkingOptimizer()
    with patch(
        "apps.content.internal_linking.linking_optimizer.get_linking_optimizer",
        return_value=engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "audit_internal_links",
            {
                "site_niche": "yoga",
                "pages": [
                    {"url": "/a", "title": "Page A", "word_count": 500, "keywords": ["yoga"]},
                    {"url": "/b", "title": "Page B", "word_count": 100, "keywords": ["yoga"]},
                ],
            },
        )

    assert media == {}
    assert "Internal linking audit" in obs


async def test_audit_internal_links_requires_pages():
    mind = AriaMind()
    obs, media = await mind._execute_tool("audit_internal_links", {"site_niche": "yoga"})

    assert media == {}
    assert "pages" in obs.lower()


async def test_suggest_internal_links_reachable_from_tool_dispatch():
    engine = LinkingOptimizer()
    with patch(
        "apps.content.internal_linking.linking_optimizer.get_linking_optimizer",
        return_value=engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "suggest_internal_links",
            {
                "source_page": {"url": "/a", "title": "Page A", "keywords": ["yoga"]},
                "content_library": [{"url": "/b", "title": "Page B", "keywords": ["yoga"]}],
            },
        )

    assert media == {}
    assert "Internal link suggestions" in obs


async def test_generate_pillar_strategy_reachable_from_tool_dispatch():
    engine = LinkingOptimizer()
    with patch(
        "apps.content.internal_linking.linking_optimizer.get_linking_optimizer",
        return_value=engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "generate_pillar_strategy", {"niche": "yoga", "topics": ["poses", "breathing"]}
        )

    assert media == {}
    assert "Pillar-cluster strategy for yoga" in obs


async def test_internal_linking_stats_empty_state():
    engine = LinkingOptimizer()
    with patch(
        "apps.content.internal_linking.linking_optimizer.get_linking_optimizer",
        return_value=engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("internal_linking_stats", {})

    assert media == {}
    assert "no internal linking activity" in obs.lower()


# ── EngagementPredictor / ViralityEngine ───────────────────────────────
async def test_predict_engagement_reachable_from_tool_dispatch():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "predict_engagement",
        {"content": "How to master yoga in 7 days?", "platform": "tiktok"},
    )

    assert media == {}
    assert "Engagement prediction (tiktok)" in obs
    assert "heuristic estimate" in obs.lower()


async def test_predict_engagement_requires_content():
    mind = AriaMind()
    obs, media = await mind._execute_tool("predict_engagement", {})

    assert media == {}
    assert "content" in obs.lower()


async def test_analyze_virality_reachable_from_tool_dispatch():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "analyze_virality", {"content": "The secret truth nobody tells you about yoga"}
    )

    assert media == {}
    assert "Virality analysis" in obs


async def test_optimize_viral_title_reachable_from_tool_dispatch():
    mind = AriaMind()
    obs, media = await mind._execute_tool("optimize_viral_title", {"title": "Yoga tips"})

    assert media == {}
    assert "Viral title alternatives" in obs


# ── ReinforcementOptimizer ─────────────────────────────────────────────
async def test_select_growth_action_reachable_from_tool_dispatch():
    engine = ReinforcementOptimizer()
    with patch(
        "apps.learning.optimization.reinforcement_optimizer.get_reinforcement_optimizer",
        return_value=engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("select_growth_action", {})

    assert media == {}
    assert "Recommended next growth action" in obs


async def test_record_action_outcome_reachable_from_tool_dispatch():
    engine = ReinforcementOptimizer()
    with patch(
        "apps.learning.optimization.reinforcement_optimizer.get_reinforcement_optimizer",
        return_value=engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "record_action_outcome", {"action_type": "flash_sale", "reward": 42.0}
        )

    assert media == {}
    assert "flash_sale" in obs


async def test_reinforcement_report_empty_state():
    engine = ReinforcementOptimizer()
    with patch(
        "apps.learning.optimization.reinforcement_optimizer.get_reinforcement_optimizer",
        return_value=engine,
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("reinforcement_report", {})

    assert media == {}
    assert "no growth actions logged" in obs.lower()


async def test_roi_and_cashflow_tools_blocked_for_non_owner():
    """A security-audit pass found these persist to a single Redis key
    shared by every user (economics:roi:v1, business:cashflow:v1) — any
    signed-in non-owner user could corrupt the owner's real financial
    ledger. They're now owner-only."""
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "record_cashflow_entry",
        {"type": "income", "amount": 999999, "category": "sales"},
        email="someone@else.com",
    )

    assert media == {}
    assert "owner" in obs.lower()


# ── ROITracker ──────────────────────────────────────────────────────────
async def test_track_roi_and_update_returns_flow():
    engine = ROITracker()
    with patch("apps.economics.roi_tracker.get_roi_tracker", return_value=engine):
        mind = AriaMind()
        track_obs, _ = await mind._execute_tool(
            "track_roi",
            {"name": "Spring campaign", "category": "campaign", "investment_usd": 100},
            email=OWNER_EMAIL,
        )
        assert "Spring campaign" in track_obs
        record_id = track_obs.split("record_id `")[1].split("`")[0]

        update_obs, media = await mind._execute_tool(
            "update_roi_returns",
            {"record_id": record_id, "returns_usd": 250},
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "150.0% ROI" in update_obs


async def test_update_roi_returns_unknown_record():
    engine = ROITracker()
    with patch("apps.economics.roi_tracker.get_roi_tracker", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "update_roi_returns",
            {"record_id": "does-not-exist", "returns_usd": 10},
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "no roi record found" in obs.lower()


async def test_roi_summary_empty_state():
    engine = ROITracker()
    with patch("apps.economics.roi_tracker.get_roi_tracker", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool("roi_summary", {}, email=OWNER_EMAIL)

    assert media == {}
    assert "no roi records yet" in obs.lower()


# ── CashflowEngine ────────────────────────────────────────────────────
async def test_record_cashflow_entry_reachable_from_tool_dispatch():
    engine = CashflowEngine()
    with patch("apps.business.finance.cashflow_engine.get_cashflow_engine", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "record_cashflow_entry",
            {"type": "income", "amount": 500, "category": "sales"},
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "Recorded income: $500.00" in obs


async def test_record_cashflow_entry_requires_valid_type():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "record_cashflow_entry",
        {"type": "bogus", "amount": 10, "category": "x"},
        email=OWNER_EMAIL,
    )

    assert media == {}
    assert "income" in obs.lower() and "expense" in obs.lower()


async def test_cashflow_summary_reflects_recorded_entries():
    engine = CashflowEngine()
    with patch("apps.business.finance.cashflow_engine.get_cashflow_engine", return_value=engine):
        mind = AriaMind()
        await mind._execute_tool(
            "record_cashflow_entry",
            {"type": "income", "amount": 1000, "category": "sales"},
            email=OWNER_EMAIL,
        )
        await mind._execute_tool(
            "record_cashflow_entry",
            {"type": "expense", "amount": 300, "category": "ads"},
            email=OWNER_EMAIL,
        )
        obs, media = await mind._execute_tool("cashflow_summary", {}, email=OWNER_EMAIL)

    assert media == {}
    assert "$700.00" in obs


async def test_forecast_cashflow_reachable_from_tool_dispatch():
    engine = CashflowEngine()
    with patch("apps.business.finance.cashflow_engine.get_cashflow_engine", return_value=engine):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "forecast_cashflow", {"months_ahead": 2}, email=OWNER_EMAIL
        )

    assert media == {}
    assert "Cashflow forecast" in obs
    assert "Month 1" in obs and "Month 2" in obs
