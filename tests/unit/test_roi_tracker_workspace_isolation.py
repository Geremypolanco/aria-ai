"""ROITracker as the second module converted to per-workspace storage
(apps/core/tenancy.py), following the exact pattern established by
apps/business/finance/cashflow_engine.py (see
test_tenancy_and_cashflow_isolation.py).

ROITracker used to persist every record to ONE hardcoded global Redis key
("economics:roi:v1") regardless of caller, so every team's ROI records were
actually the same records. It's now keyed per workspace_id, with the same
narrowly-scoped one-time fallback to the old global key — applied ONLY to
the real owner's own workspace_id — so the owner's pre-existing production
records aren't silently orphaned by the key-format change without leaking
into any other tenant's first read.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.economics.roi_tracker import ROITracker, get_roi_tracker

pytestmark = pytest.mark.asyncio


def _mock_cache(get_return=None):
    c = MagicMock()
    c.get = AsyncMock(return_value=get_return)
    c.set = AsyncMock(return_value=True)
    return c


async def test_two_workspaces_never_share_a_cache_key():
    tracker_a = ROITracker("workspace-a@example.com")
    tracker_b = ROITracker("workspace-b@example.com")
    assert tracker_a._cache_key != tracker_b._cache_key
    assert "workspace-a@example.com" in tracker_a._cache_key
    assert "workspace-b@example.com" in tracker_b._cache_key


async def test_get_roi_tracker_returns_distinct_instances_per_workspace():
    tracker_a = get_roi_tracker("workspace-a@example.com")
    tracker_b = get_roi_tracker("workspace-b@example.com")
    assert tracker_a is not tracker_b
    assert get_roi_tracker("workspace-a@example.com") is tracker_a


async def test_tracking_for_one_workspace_never_touches_anothers_records():
    cache_a, cache_b = _mock_cache(), _mock_cache()
    current_cache = [cache_a]

    def fake_get_cache():
        return current_cache[0]

    with patch("apps.economics.roi_tracker.get_cache", side_effect=fake_get_cache):
        tracker_a = ROITracker("workspace-a@example.com")
        await tracker_a.track("Campaign A", "campaign", 100.0)

        current_cache[0] = cache_b
        tracker_b = ROITracker("workspace-b@example.com")
        await tracker_b.track("Campaign B", "campaign", 50.0)

    cache_a.set.assert_awaited_once()
    saved_key_a, saved_data_a = cache_a.set.call_args[0][0], cache_a.set.call_args[0][1]
    assert saved_key_a == tracker_a._cache_key
    assert len(saved_data_a["records"]) == 1
    assert saved_data_a["records"][0]["name"] == "Campaign A"

    cache_b.set.assert_awaited_once()
    saved_key_b, saved_data_b = cache_b.set.call_args[0][0], cache_b.set.call_args[0][1]
    assert saved_key_b == tracker_b._cache_key
    assert len(saved_data_b["records"]) == 1
    assert saved_data_b["records"][0]["name"] == "Campaign B"


async def test_non_owner_workspace_with_no_records_never_inherits_the_legacy_ledger():
    legacy_data = {"records": [{"name": "owner-only campaign", "investment_usd": 999999.0}]}
    cache = _mock_cache()

    async def fake_get(key):
        if key == "economics:roi:v1":
            return legacy_data
        return None

    cache.get = AsyncMock(side_effect=fake_get)

    with (
        patch("apps.economics.roi_tracker.get_cache", return_value=cache),
        patch("apps.core.auth.owner_emails", return_value={"real-owner@example.com"}),
    ):
        tracker = ROITracker("brand-new-team@example.com")
        await tracker._load()

    assert tracker._records == []


async def test_the_real_owners_own_workspace_inherits_the_legacy_ledger_once():
    legacy_data = {"records": [{"name": "legacy campaign", "investment_usd": 5000.0}]}
    cache = _mock_cache()

    async def fake_get(key):
        if key == "economics:roi:v1":
            return legacy_data
        return None

    cache.get = AsyncMock(side_effect=fake_get)

    with (
        patch("apps.economics.roi_tracker.get_cache", return_value=cache),
        patch("apps.core.auth.owner_emails", return_value={"real-owner@example.com"}),
    ):
        tracker = ROITracker("real-owner@example.com")
        await tracker._load()

    assert tracker._records == legacy_data["records"]
