"""Regression test: shopify_get_orders() built its request URL directly from
settings.SHOPIFY_URL without stripping a scheme prefix, unlike its sibling
shopify_create_product() which explicitly normalizes for this (comment:
"env var may include https://"). If SHOPIFY_URL is set with a scheme
prefix, the un-normalized version produced a malformed double-scheme URL
like https://https://mystore.myshopify.com/... that fails outright.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.tools.commerce_tools import CommerceTools

pytestmark = pytest.mark.asyncio


async def test_shopify_get_orders_normalizes_url_with_scheme_prefix(monkeypatch):
    monkeypatch.setattr(
        "apps.core.tools.commerce_tools.settings.SHOPIFY_URL", "https://mystore.myshopify.com"
    )
    monkeypatch.setattr("apps.core.tools.commerce_tools.settings.SHOPIFY_ADMIN_TOKEN", "tok")
    monkeypatch.setattr("apps.core.tools.commerce_tools.settings.SHOPIFY_AUTOMATION_TOKEN", None)

    tools = CommerceTools()
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"orders": []}

    captured_url = {}

    async def fake_get(url, **kwargs):
        captured_url["url"] = url
        return fake_resp

    with patch.object(tools._http, "get", fake_get):
        await tools.shopify_get_orders()

    assert captured_url["url"] == "https://mystore.myshopify.com/admin/api/2024-01/orders.json"
    assert "https://https://" not in captured_url["url"]
