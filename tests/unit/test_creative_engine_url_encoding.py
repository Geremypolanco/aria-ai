"""Regression test: CreativeEngine.create_image() and .take_screenshot()
embedded caller-supplied text directly into query strings without proper
URL-encoding.

- create_image() did prompt.replace(' ', '%20') — any other special char
  (&, #, ?, %) in the prompt would corrupt the Pollinations URL or inject
  extra query params. content_operator.py already uses the correct
  urllib.parse.quote() pattern for this identical API.
- take_screenshot() embedded the target `url` (which itself commonly
  contains query params, e.g. real Shopify product URLs from
  ecommerce_agent.py) directly as a query value with zero encoding,
  splitting the screenshotlayer.com request into unintended parameters.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.tools.creative_engine import CreativeEngine

pytestmark = pytest.mark.asyncio


async def test_create_image_url_encodes_special_characters():
    engine = CreativeEngine()
    with patch("apps.core.tools.zapier_connector.ZapierConnector") as mock_zap_cls:
        mock_zap_cls.return_value.dispatch_event = AsyncMock()
        mock_zap_cls.return_value.EVENT_CREATION_READY = "creation_ready"
        result = await engine.create_image("cats & dogs playing #fun")
    assert "&" not in result["url"].split("/prompt/")[1].split("?")[0]
    assert "%26" in result["url"] or "cats%20%26%20dogs" in result["url"]


async def test_take_screenshot_url_encodes_target_url_with_query_params(monkeypatch):
    monkeypatch.setattr(
        "apps.core.tools.creative_engine.settings.SCREENSHOT_API_KEY", "fake-key"
    )
    engine = CreativeEngine()

    captured = {}

    async def fake_get(url, *a, **k):
        captured["url"] = url
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"fake png bytes"
        return resp

    with patch.object(engine._http, "get", fake_get), patch(
        "apps.core.tools.content_tools.ContentTools"
    ) as mock_ct_cls:
        mock_ct_cls.return_value.cloudinary_upload = AsyncMock(return_value={"success": True})
        await engine.take_screenshot("https://shop.example.com/products/x?variant=1&ref=ads")

    # The target URL's own query string must be percent-encoded so it can't
    # inject extra parameters into the screenshotlayer.com request.
    assert "variant=1&ref=ads" not in captured["url"]
    assert "variant%3D1%26ref%3Dads" in captured["url"]
