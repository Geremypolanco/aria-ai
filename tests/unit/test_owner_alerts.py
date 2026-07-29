"""apps/core/notifications/owner_alerts.py — real-time owner email alerts on
first login / plan purchased / subscription canceled, plus a weekly digest
built from the same real funnel counters main.py's _track() already writes
(never a second, invented set of numbers).

notify_owner() must resolve its destination through apps.core.auth.
owner_emails() — the single source of truth for "who is the owner" already
used to gate /admin — not a second hardcoded address that could drift.

weekly_report_loop()'s restart-survival property (state persisted in Redis,
not a long in-process sleep) is exercised through
_check_and_maybe_send_weekly_report(), the same reasoning already applied
to the income loop in tests/unit/test_income_loop_resume_on_restart.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.notifications import owner_alerts

pytestmark = pytest.mark.asyncio


def _fake_cache(store: dict | None = None):
    store = store if store is not None else {}
    cache = AsyncMock()

    async def get(key):
        return store.get(key)

    async def set_(key, value, ttl_seconds=None):
        store[key] = value
        return True

    async def set_if_not_exists(key, value, ttl_seconds=None):
        if key in store:
            return False
        store[key] = value
        return True

    async def increment(key):
        store[key] = int(store.get(key, 0)) + 1
        return store[key]

    async def increment_by(key, amount):
        store[key] = float(store.get(key, 0.0)) + amount
        return store[key]

    cache.get = get
    cache.set = set_
    cache.set_if_not_exists = set_if_not_exists
    cache.increment = increment
    cache.increment_by = increment_by
    return cache, store


# ── notify_owner ─────────────────────────────────────────────────────────


async def test_notify_owner_sends_to_the_single_source_of_truth_owner_email():
    send = AsyncMock(return_value={"success": True, "provider": "resend"})
    with (
        patch("apps.core.auth.owner_emails", return_value={"geremypolancod@gmail.com"}),
        patch("apps.core.tools.publishing_tools.PublishingTools.send_newsletter", send),
    ):
        await owner_alerts.notify_owner("subject", "body")

    send.assert_awaited_once_with("subject", "body", to_override="geremypolancod@gmail.com")


async def test_notify_owner_never_raises_on_send_failure():
    with (
        patch("apps.core.auth.owner_emails", return_value={"geremypolancod@gmail.com"}),
        patch(
            "apps.core.tools.publishing_tools.PublishingTools.send_newsletter",
            AsyncMock(side_effect=RuntimeError("smtp down")),
        ),
    ):
        await owner_alerts.notify_owner("subject", "body")  # must not raise


async def test_notify_owner_does_nothing_without_a_configured_owner_email():
    send = AsyncMock()
    with (
        patch("apps.core.auth.owner_emails", return_value=set()),
        patch("apps.core.tools.publishing_tools.PublishingTools.send_newsletter", send),
    ):
        await owner_alerts.notify_owner("subject", "body")

    send.assert_not_awaited()


# ── notify_first_login ───────────────────────────────────────────────────


async def test_notify_first_login_fires_exactly_once_per_email():
    cache, store = _fake_cache()
    send = AsyncMock(return_value={"success": True})
    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch("apps.core.auth.owner_emails", return_value={"geremypolancod@gmail.com"}),
        patch("apps.core.tools.publishing_tools.PublishingTools.send_newsletter", send),
    ):
        await owner_alerts.notify_first_login("new@example.com", "New User", "email")
        await owner_alerts.notify_first_login("new@example.com", "New User", "email")

    send.assert_awaited_once()
    assert store.get("aria:track:first_login:total") == 1


async def test_notify_first_login_does_nothing_without_an_email():
    send = AsyncMock()
    with patch("apps.core.tools.publishing_tools.PublishingTools.send_newsletter", send):
        await owner_alerts.notify_first_login("", "Name", "email")

    send.assert_not_awaited()


# ── notify_plan_purchased / notify_subscription_canceled ────────────────


async def test_notify_plan_purchased_tracks_revenue_and_notifies():
    cache, store = _fake_cache()
    send = AsyncMock(return_value={"success": True})
    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch("apps.core.auth.owner_emails", return_value={"geremypolancod@gmail.com"}),
        patch("apps.core.tools.publishing_tools.PublishingTools.send_newsletter", send),
    ):
        await owner_alerts.notify_plan_purchased("buyer@example.com", "pro", 49.0)

    send.assert_awaited_once()
    subject, body = send.await_args.args[:2]
    assert "buyer@example.com" in subject
    assert "49.00" in body
    assert any(k.startswith("aria:track:revenue_usd:") for k in store)


async def test_notify_subscription_canceled_notifies():
    cache, _ = _fake_cache()
    send = AsyncMock(return_value={"success": True})
    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch("apps.core.auth.owner_emails", return_value={"geremypolancod@gmail.com"}),
        patch("apps.core.tools.publishing_tools.PublishingTools.send_newsletter", send),
    ):
        await owner_alerts.notify_subscription_canceled("leaving@example.com")

    send.assert_awaited_once()
    assert "leaving@example.com" in send.await_args.args[0]


# ── weekly rollup + diagnosis ────────────────────────────────────────────


async def test_diagnose_flags_zero_traffic_first():
    weekly = dict.fromkeys(owner_alerts._FUNNEL_EVENTS, 0) | {"_revenue_usd": 0.0}
    assert "Nobody visited" in owner_alerts._diagnose(weekly)


async def test_diagnose_flags_signup_page_dropoff():
    weekly = dict.fromkeys(owner_alerts._FUNNEL_EVENTS, 0) | {
        "landing_view": 50,
        "_revenue_usd": 0.0,
    }
    assert "zero people reached" in owner_alerts._diagnose(weekly)


async def test_diagnose_notes_healthy_week_when_everything_converted():
    weekly = dict.fromkeys(owner_alerts._FUNNEL_EVENTS, 3) | {
        "subscription_canceled": 0,
        "_revenue_usd": 147.0,
    }
    result = owner_alerts._diagnose(weekly)
    assert "147.00" in result
    assert "next lever" in result


async def test_build_weekly_report_uses_real_rollup_numbers():
    async def fake_rollup():
        return dict.fromkeys(owner_alerts._FUNNEL_EVENTS, 0) | {
            "landing_view": 12,
            "_revenue_usd": 0.0,
        }

    with patch.object(owner_alerts, "_weekly_rollup", fake_rollup):
        report = await owner_alerts.build_weekly_report()

    assert "Landing page views: 12" in report
    assert "Revenue: $0.00" in report


# ── restart-safe weekly send ──────────────────────────────────────────────


async def test_weekly_report_sends_when_a_week_has_elapsed():
    cache, store = _fake_cache({owner_alerts._WEEKLY_REPORT_LAST_SENT_KEY: "0"})
    send = AsyncMock(return_value={"success": True})
    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch("apps.core.auth.owner_emails", return_value={"geremypolancod@gmail.com"}),
        patch("apps.core.tools.publishing_tools.PublishingTools.send_newsletter", send),
    ):
        sent = await owner_alerts._check_and_maybe_send_weekly_report()

    assert sent is True
    send.assert_awaited_once()
    assert float(store[owner_alerts._WEEKLY_REPORT_LAST_SENT_KEY]) > 0


async def test_weekly_report_does_not_resend_within_the_same_week():
    import time

    cache, _ = _fake_cache({owner_alerts._WEEKLY_REPORT_LAST_SENT_KEY: str(time.time())})
    send = AsyncMock(return_value={"success": True})
    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch("apps.core.tools.publishing_tools.PublishingTools.send_newsletter", send),
    ):
        sent = await owner_alerts._check_and_maybe_send_weekly_report()

    assert sent is False
    send.assert_not_awaited()


async def test_weekly_report_survives_across_a_simulated_restart():
    """Two separate check calls (simulating two process restarts) sharing
    only the persisted Redis state must still send exactly once once a week
    has passed, and never twice for the same week."""
    import time

    cache, store = _fake_cache(
        {owner_alerts._WEEKLY_REPORT_LAST_SENT_KEY: str(time.time() - 8 * 86400)}
    )
    send = AsyncMock(return_value={"success": True})
    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch("apps.core.auth.owner_emails", return_value={"geremypolancod@gmail.com"}),
        patch("apps.core.tools.publishing_tools.PublishingTools.send_newsletter", send),
    ):
        first = await owner_alerts._check_and_maybe_send_weekly_report()
        second = await owner_alerts._check_and_maybe_send_weekly_report()

    assert first is True
    assert second is False
    send.assert_awaited_once()
