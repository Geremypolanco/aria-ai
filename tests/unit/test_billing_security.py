"""Regression tests for the /billing/success session-replay/account-mismatch
fix: a Stripe checkout session_id must only grant a plan to the account that
actually paid, and only once."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core import main

pytestmark = pytest.mark.asyncio


def _request(cookie_email="buyer@example.com"):
    req = MagicMock()
    req.cookies = {"aria_user": "signed-token"} if cookie_email else {}
    req._email = cookie_email
    return req


def _stripe_session(email="buyer@example.com", tier="pro", paid=True):
    return {
        "payment_status": "paid" if paid else "unpaid",
        "status": "complete" if paid else "open",
        "metadata": {"email": email, "tier": tier},
    }


@pytest.fixture(autouse=True)
def _patch_cache():
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        yield cache


async def test_grants_plan_when_requester_paid():
    req = _request("buyer@example.com")
    with patch("apps.core.auth.verify_user", return_value={"email": "buyer@example.com"}), \
         patch("stripe.checkout.Session.retrieve", return_value=_stripe_session(email="buyer@example.com")), \
         patch.object(main, "_set_user_plan", new=AsyncMock()) as set_plan, \
         patch.object(main.settings, "STRIPE_SECRET_KEY", "sk_test"):
        await main.billing_success(req, session_id="cs_123")
    set_plan.assert_awaited_once_with("buyer@example.com", "pro")


async def test_rejects_when_logged_in_account_did_not_pay():
    """A leaked/shared session_id must not let a different logged-in account
    claim the plan the original buyer paid for."""
    req = _request("attacker@example.com")
    with patch("apps.core.auth.verify_user", return_value={"email": "attacker@example.com"}), \
         patch("stripe.checkout.Session.retrieve", return_value=_stripe_session(email="victim@example.com")), \
         patch.object(main, "_set_user_plan", new=AsyncMock()) as set_plan, \
         patch.object(main.settings, "STRIPE_SECRET_KEY", "sk_test"):
        await main.billing_success(req, session_id="cs_leaked")
    set_plan.assert_not_awaited()


async def test_rejects_unpaid_session():
    req = _request("buyer@example.com")
    with patch("apps.core.auth.verify_user", return_value={"email": "buyer@example.com"}), \
         patch("stripe.checkout.Session.retrieve", return_value=_stripe_session(email="buyer@example.com", paid=False)), \
         patch.object(main, "_set_user_plan", new=AsyncMock()) as set_plan, \
         patch.object(main.settings, "STRIPE_SECRET_KEY", "sk_test"):
        await main.billing_success(req, session_id="cs_unpaid")
    set_plan.assert_not_awaited()


async def test_does_not_regrant_a_consumed_session(_patch_cache):
    _patch_cache.get = AsyncMock(return_value="1")  # already consumed
    req = _request("buyer@example.com")
    with patch("apps.core.auth.verify_user", return_value={"email": "buyer@example.com"}), \
         patch("stripe.checkout.Session.retrieve", return_value=_stripe_session(email="buyer@example.com")), \
         patch.object(main, "_set_user_plan", new=AsyncMock()) as set_plan, \
         patch.object(main.settings, "STRIPE_SECRET_KEY", "sk_test"):
        await main.billing_success(req, session_id="cs_reused")
    set_plan.assert_not_awaited()
