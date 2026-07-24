"""Regression test: MultimodalEngine (analyze_image/edit_image/
remove_background/analyze_video_url) fetched user-supplied image/video URLs
directly with no validation — the same SSRF class fixed in web_tools.py and
browser_sandbox.py, present a third (and, in huggingface_suite.py, fourth)
time."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.core.tools.huggingface_suite import HuggingFaceSuite
from apps.core.tools.multimodal import MultimodalEngine

pytestmark = pytest.mark.asyncio


async def test_analyze_image_refuses_internal_url():
    engine = MultimodalEngine()
    result = await engine.analyze_image(image_url="http://169.254.169.254/latest/meta-data/")
    assert result["success"] is False


async def test_edit_image_refuses_internal_url(monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.HF_TOKEN", "fake-token")
    engine = MultimodalEngine()
    result = await engine.edit_image(image_url="http://127.0.0.1/admin", instruction="test")
    assert result["success"] is False


async def test_analyze_video_url_refuses_internal_url():
    engine = MultimodalEngine()
    result = await engine.analyze_video_url("http://10.0.0.5/secret.mp4")
    assert result["success"] is False


async def test_hf_describe_image_refuses_internal_url():
    with patch("apps.core.config.settings.HF_TOKEN", "fake-token"):
        suite = HuggingFaceSuite()
        result = await suite.describe_image(image_url="http://169.254.169.254/latest/meta-data/")
    assert result["success"] is False
