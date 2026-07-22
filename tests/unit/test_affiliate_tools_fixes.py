"""Regression tests for bugs found auditing affiliate_tools.py:

1. search_amazon_products()/capability_report() read settings via
   getattr(settings, "AMAZON_PA_ACCESS_KEY"/"AMAZON_PA_SECRET_KEY"/
   "AMAZON_PA_PARTNER_TAG", None) — none of these three names are declared
   fields on the Settings model. The real fields (already used by
   apps/core/connections/ecommerce_connection.py for the same PA API) are
   AMAZON_ACCESS_KEY, AMAZON_SECRET_KEY, AMAZON_ASSOCIATE_TAG. Since getattr's
   3-arg form swallows AttributeError, this silently and permanently
   disabled Amazon product search regardless of what the operator configured.
2. build_hotmart_link()/capability_report() read HOTMART_AFFILIATE_ID, which
   didn't exist as a Settings field at all — added it.
3. search_amazon_products() indexed item["Offers"]["Listings"][0] via
   `.get("Listings", [{}])[0]`, which crashes with IndexError whenever
   "Listings" is present but an empty list (the [{}] default only applies
   when the key is absent), breaking the entire search for every item once
   one item lacked pricing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.core.tools.affiliate_tools import AffiliateTools


@pytest.mark.asyncio
async def test_search_amazon_products_reports_real_missing_field_names(monkeypatch):
    monkeypatch.setattr("apps.core.tools.affiliate_tools.settings.AMAZON_ACCESS_KEY", None)
    monkeypatch.setattr("apps.core.tools.affiliate_tools.settings.AMAZON_SECRET_KEY", None)
    monkeypatch.setattr("apps.core.tools.affiliate_tools.settings.AMAZON_ASSOCIATE_TAG", None)

    tools = AffiliateTools()
    result = await tools.search_amazon_products("wireless mouse")

    assert result["success"] is False
    assert "AMAZON_ACCESS_KEY" in result["error"]
    assert "AMAZON_SECRET_KEY" in result["error"]
    assert "AMAZON_ASSOCIATE_TAG" in result["error"]


async def test_search_amazon_products_calls_api_when_real_fields_configured(monkeypatch):
    monkeypatch.setattr("apps.core.tools.affiliate_tools.settings.AMAZON_ACCESS_KEY", "AKIA_FAKE")
    monkeypatch.setattr("apps.core.tools.affiliate_tools.settings.AMAZON_SECRET_KEY", "fake-secret")
    monkeypatch.setattr("apps.core.tools.affiliate_tools.settings.AMAZON_ASSOCIATE_TAG", "mytag-20")

    tools = AffiliateTools()

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "SearchResult": {
            "Items": [
                {
                    "ASIN": "B0TEST123",
                    "ItemInfo": {"Title": {"DisplayValue": "Test Mouse"}},
                    "Offers": {"Listings": []},
                    "Images": {"Primary": {"Medium": {"URL": "http://img"}}},
                }
            ]
        }
    }
    tools._http.post = AsyncMock(return_value=fake_resp)

    result = await tools.search_amazon_products("wireless mouse")

    assert result["success"] is True
    assert result["products"][0]["price"] == "N/A"


def test_hotmart_affiliate_id_is_a_real_settings_field():
    from apps.core.config import settings

    assert hasattr(settings, "HOTMART_AFFILIATE_ID")


def test_build_hotmart_link_uses_configured_id(monkeypatch):
    monkeypatch.setattr(
        "apps.core.tools.affiliate_tools.settings.HOTMART_AFFILIATE_ID", "hm-affiliate-1"
    )
    tools = AffiliateTools()

    result = tools.build_hotmart_link("prod123")

    assert result["success"] is True
    assert "hm-affiliate-1" in result["link"]
