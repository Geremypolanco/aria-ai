"""Regression test: the Stripe webhook's checkout.session.completed handler
granted the paid plan but never recorded the actual revenue anywhere —
AriaMetrics.record_income_cycle() was never called by any live code path, so
admin_overview()'s revenue_usd/net_margin_usd always read 0.0 regardless of
real Stripe revenue, permanently showing the business as unprofitable on the
owner's God Mode console. Fixed to record the real amount_total from the
checkout session."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core import main

pytestmark = pytest.mark.asyncio


def _fake_request(sig="sig_test") -> MagicMock:
    req = MagicMock()
    req.body = AsyncMock(return_value=b"{}")
    req.headers = {"stripe-signature": sig}
    return req


def _checkout_completed_event(
    email="buyer@example.com", tier="pro", paid=True, amount_total_cents=2900
):
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "payment_status": "paid" if paid else "unpaid",
                "amount_total": amount_total_cents,
                "metadata": {"email": email, "tier": tier},
            }
        },
    }


async def test_paid_checkout_records_real_revenue_in_dollars():
    event = _checkout_completed_event(amount_total_cents=2900)  # $29.00
    fake_metrics = MagicMock()
    with (
        patch.object(main.settings, "STRIPE_WEBHOOK_SECRET", "whsec_test"),
        patch("stripe.Webhook.construct_event", return_value=event),
        patch.object(main, "_set_user_plan", new=AsyncMock()),
        patch("apps.core.observability.metrics.get_metrics", return_value=fake_metrics),
    ):
        await main.billing_webhook(_fake_request())

    fake_metrics.record_income_cycle.assert_called_once_with(success=True, revenue_usd=29.0)


async def test_unpaid_checkout_does_not_record_revenue():
    event = _checkout_completed_event(paid=False)
    fake_metrics = MagicMock()
    with (
        patch.object(main.settings, "STRIPE_WEBHOOK_SECRET", "whsec_test"),
        patch("stripe.Webhook.construct_event", return_value=event),
        patch.object(main, "_set_user_plan", new=AsyncMock()) as set_plan,
        patch("apps.core.observability.metrics.get_metrics", return_value=fake_metrics),
    ):
        await main.billing_webhook(_fake_request())

    set_plan.assert_not_awaited()
    fake_metrics.record_income_cycle.assert_not_called()


async def test_unrelated_event_type_does_not_record_revenue():
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"metadata": {"email": "buyer@example.com"}, "status": "active"}},
    }
    fake_metrics = MagicMock()
    with (
        patch.object(main.settings, "STRIPE_WEBHOOK_SECRET", "whsec_test"),
        patch("stripe.Webhook.construct_event", return_value=event),
        patch("apps.core.observability.metrics.get_metrics", return_value=fake_metrics),
    ):
        await main.billing_webhook(_fake_request())

    fake_metrics.record_income_cycle.assert_not_called()
