"""Regression test: _exec_stripe_subscription() computed
`int(sub_data.get("annual_price_cents", 18000))` as a bare, unassigned
statement — the AI prompt explicitly asks for and returns an annual price,
but the value was discarded immediately, so the "subscription product"
strategy always only ever created a monthly Stripe Price/payment link,
regardless of what annual pricing the AI generated. Fixed to actually
create a mirrored annual Price + payment link (paralleling the existing
monthly flow) and surface it on the generated landing page.
"""

from __future__ import annotations

import httpx
import pytest

from apps.core.tools.income_loop import IncomeLoop

pytestmark = pytest.mark.asyncio


async def test_stripe_subscription_creates_and_uses_annual_price(monkeypatch):
    loop = IncomeLoop.__new__(IncomeLoop)

    fake_sub_data = {
        "name": "AI Toolkit Pro",
        "tagline": "Everything you need",
        "monthly_price_cents": 1900,
        "annual_price_cents": 18000,
        "description": "A" * 210,
        "monthly_deliverables": ["d1", "d2"],
        "tier_name": "Pro",
        "trial_days": 7,
        "target_mrr": 1000,
    }

    async def fake_complete_json(self, *a, **k):
        return fake_sub_data

    async def fake_trending(self, *a, **k):
        return {"success": False}

    created_prices = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/products":
            return httpx.Response(200, json={"id": "prod_123"})
        if path == "/v1/prices":
            body = dict(x.split("=") for x in request.content.decode().split("&"))
            interval = body.get("recurring%5Binterval%5D", "")
            created_prices.append(interval)
            price_id = "price_month" if "month" in interval else "price_year"
            return httpx.Response(200, json={"id": price_id})
        if path == "/v1/payment_links":
            body = request.content.decode()
            if "price_year" in body:
                return httpx.Response(200, json={"url": "https://buy.stripe.com/annual"})
            return httpx.Response(200, json={"url": "https://buy.stripe.com/monthly"})
        return httpx.Response(404)

    _real_async_client = httpx.AsyncClient

    class FakeAsyncClient:
        def __init__(self, *a, **k):
            self._client = _real_async_client(transport=httpx.MockTransport(handler))

        async def __aenter__(self):
            return self._client

        async def __aexit__(self, *a):
            await self._client.aclose()

    monkeypatch.setattr(
        "apps.core.tools.ai_client.get_ai_client",
        lambda: type("C", (), {"complete_json": fake_complete_json})(),
    )
    monkeypatch.setattr(IncomeLoop, "_get_trending_context", fake_trending, raising=False)
    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("apps.core.tools.income_loop.settings.STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setattr("apps.core.tools.income_loop.settings.GITHUB_TOKEN", None)
    monkeypatch.setattr("apps.core.tools.income_loop.settings.GUMROAD_TOKEN", None)
    monkeypatch.setattr("apps.core.tools.income_loop.settings.ARIA_EMAIL", None)
    monkeypatch.setattr("apps.core.tools.income_loop.settings.ARIA_PASSWORD", None)

    result = await loop._exec_stripe_subscription()

    assert "month" in created_prices[0] or "month" in "".join(created_prices)
    assert any("year" in p for p in created_prices), "annual Stripe Price was never created"
    assert isinstance(result, dict)
