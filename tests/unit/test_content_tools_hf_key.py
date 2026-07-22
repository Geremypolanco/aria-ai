"""Regression test: ContentTools.flux_generate_image() checked
settings.HF_TOKEN directly instead of the canonical settings.hf_key
property (HF_TOKEN or HF_API_KEY or HUGGING_FACE_TOKEN) that every other
HuggingFace-consuming file in this codebase relies on. A deployment that
only sets HF_API_KEY or HUGGING_FACE_TOKEN (not HF_TOKEN specifically)
would incorrectly get "HF_TOKEN no configurado" from this function alone,
while every other HF call site in the app worked fine.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.tools.content_tools import ContentTools

pytestmark = pytest.mark.asyncio


async def test_flux_generate_image_works_with_hf_api_key_fallback(monkeypatch):
    monkeypatch.setattr("apps.core.tools.content_tools.settings.HF_TOKEN", None)
    monkeypatch.setattr("apps.core.tools.content_tools.settings.HF_API_KEY", "fallback-key")
    monkeypatch.setattr("apps.core.tools.content_tools.settings.HUGGING_FACE_TOKEN", None)

    tools = ContentTools()
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {"content-type": "image/jpeg"}
    fake_resp.content = b"fake image bytes"

    captured_headers = {}

    async def fake_post(url, headers=None, json=None, **kwargs):
        captured_headers.update(headers or {})
        return fake_resp

    with patch.object(tools._http, "post", fake_post):
        result = await tools.flux_generate_image("a cat")

    assert result["success"] is True
    assert captured_headers["Authorization"] == "Bearer fallback-key"
