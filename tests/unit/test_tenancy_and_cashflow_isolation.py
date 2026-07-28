"""Tests for the first phase of converting ARIA's single-tenant business
tools to per-workspace isolation:

  - apps/core/tenancy.py's workspace_id_for(): the team owner's email for a
    member (apps/core/seats.py), else the caller's own email.
  - apps/business/finance/cashflow_engine.py as the reference conversion:
    CashflowEngine used to persist to ONE hardcoded global Redis key
    ("business:cashflow:v1") regardless of caller, so every team's ledger
    was actually the same ledger. It's now keyed per workspace_id, with a
    narrowly-scoped one-time fallback to the old global key so the actual
    owner's pre-existing production ledger isn't silently orphaned by the
    key-format change.

The critical case under test for the fallback: it must apply ONLY to the
real owner's own workspace_id, never to any other/new workspace — a naive
"fall back to the legacy key whenever my own key is empty" rule would leak
the owner's entire historical ledger into every new team's first read,
which is exactly the cross-tenant bug this conversion exists to close.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.business.finance.cashflow_engine import CashflowEngine, get_cashflow_engine
from apps.core.tenancy import workspace_id_for

pytestmark = pytest.mark.asyncio


def _mock_cache(get_return=None):
    c = MagicMock()
    c.get = AsyncMock(return_value=get_return)
    c.set = AsyncMock(return_value=True)
    return c


# ── workspace_id_for ──────────────────────────────────────────────────────


async def test_workspace_id_for_returns_empty_for_blank_email():
    assert await workspace_id_for("") == ""
    assert await workspace_id_for(None) == ""


async def test_workspace_id_for_solo_user_is_their_own_workspace():
    with patch("apps.core.seats.owner_of", AsyncMock(return_value=None)):
        assert await workspace_id_for("solo@example.com") == "solo@example.com"


async def test_workspace_id_for_team_member_resolves_to_owner():
    with patch("apps.core.seats.owner_of", AsyncMock(return_value="owner@example.com")):
        assert await workspace_id_for("MEMBER@example.com  ") == "owner@example.com"


# ── CashflowEngine: per-workspace key isolation ──────────────────────────


async def test_two_workspaces_never_share_a_cache_key():
    engine_a = CashflowEngine("workspace-a@example.com")
    engine_b = CashflowEngine("workspace-b@example.com")
    assert engine_a._cache_key != engine_b._cache_key
    assert "workspace-a@example.com" in engine_a._cache_key
    assert "workspace-b@example.com" in engine_b._cache_key


async def test_get_cashflow_engine_returns_distinct_instances_per_workspace():
    engine_a = get_cashflow_engine("workspace-a@example.com")
    engine_b = get_cashflow_engine("workspace-b@example.com")
    assert engine_a is not engine_b
    # ...but the same workspace always gets the same instance back.
    assert get_cashflow_engine("workspace-a@example.com") is engine_a


async def test_recording_for_one_workspace_never_touches_anothers_data():
    """The actual isolation guarantee: entries recorded through workspace
    A's engine only ever reach workspace A's cache key."""
    cache_a, cache_b = _mock_cache(), _mock_cache()

    def fake_get_cache():
        return current_cache[0]

    current_cache = [cache_a]
    with patch("apps.business.finance.cashflow_engine.get_cache", side_effect=fake_get_cache):
        engine_a = CashflowEngine("workspace-a@example.com")
        await engine_a.record("income", 1000.0, "sales")

        current_cache[0] = cache_b
        engine_b = CashflowEngine("workspace-b@example.com")
        await engine_b.record("income", 50.0, "sales")

    # workspace A's save only ever wrote to cache_a, under its own key.
    cache_a.set.assert_awaited_once()
    saved_key_a, saved_entries_a = cache_a.set.call_args[0][0], cache_a.set.call_args[0][1]
    assert saved_key_a == engine_a._cache_key
    assert len(saved_entries_a) == 1 and saved_entries_a[0]["amount_usd"] == 1000.0

    cache_b.set.assert_awaited_once()
    saved_key_b, saved_entries_b = cache_b.set.call_args[0][0], cache_b.set.call_args[0][1]
    assert saved_key_b == engine_b._cache_key
    assert len(saved_entries_b) == 1 and saved_entries_b[0]["amount_usd"] == 50.0


# ── Legacy-key migration fallback: scoped strictly to the real owner ────


async def test_non_owner_workspace_with_no_entries_never_inherits_the_legacy_ledger():
    """The critical regression this guards against: a brand-new team's
    empty cashflow ledger must read as empty, NOT as whatever the actual
    owner's pre-multi-tenancy global ledger happened to contain."""
    legacy_data = [{"type": "income", "amount_usd": 999999.0, "category": "owner-only"}]
    cache = _mock_cache(get_return=None)

    async def fake_get(key):
        if key == "business:cashflow:v1":
            return legacy_data
        return None

    cache.get = AsyncMock(side_effect=fake_get)

    with (
        patch("apps.business.finance.cashflow_engine.get_cache", return_value=cache),
        patch("apps.core.auth.owner_emails", return_value={"real-owner@example.com"}),
    ):
        engine = CashflowEngine("brand-new-team@example.com")
        await engine._load()

    assert engine._entries == []


async def test_the_real_owners_own_workspace_inherits_the_legacy_ledger_once():
    """Continuity: the actual owner's data, written under the old global
    key before workspaces existed, must not appear to vanish."""
    legacy_data = [{"type": "income", "amount_usd": 5000.0, "category": "legacy"}]
    cache = _mock_cache()

    async def fake_get(key):
        if key == "business:cashflow:v1":
            return legacy_data
        return None

    cache.get = AsyncMock(side_effect=fake_get)

    with (
        patch("apps.business.finance.cashflow_engine.get_cache", return_value=cache),
        patch("apps.core.auth.owner_emails", return_value={"real-owner@example.com"}),
    ):
        engine = CashflowEngine("real-owner@example.com")
        await engine._load()

    assert engine._entries == legacy_data


async def test_legacy_fallback_is_skipped_once_the_workspace_has_its_own_data():
    """Once anything has been saved under the workspace-scoped key, the
    legacy key is never consulted again — the migration is one-directional
    and one-time, not an ongoing merge."""
    own_data = [{"type": "expense", "amount_usd": 10.0, "category": "new"}]
    cache = _mock_cache()
    cache.get = AsyncMock(return_value=own_data)

    with (
        patch("apps.business.finance.cashflow_engine.get_cache", return_value=cache),
        patch("apps.core.auth.owner_emails", return_value={"real-owner@example.com"}),
    ):
        engine = CashflowEngine("real-owner@example.com")
        await engine._load()

    assert engine._entries == own_data
    # get() was called exactly once — for the workspace's own key — never
    # for the legacy key, since data was already found.
    cache.get.assert_awaited_once_with(engine._cache_key)
