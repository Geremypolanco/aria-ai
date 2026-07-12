"""
Regression tests for CreativeEngine.generate_video — the fix for "ARIA no genera
videos". The old serverless HF endpoint (damo-vilab/text-to-video-ms-1.7b) was
removed by Hugging Face; video now goes through the Wan2.2 HF Space. These tests
lock in the delegation + result normalization (bytes / url-download / failure).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.config import settings
from apps.core.tools.creative_engine import CreativeEngine


@pytest.fixture(autouse=True)
def _hf_key(monkeypatch):
    monkeypatch.setattr(settings, "HF_TOKEN", "hf_test", raising=False)
    yield


async def test_no_hf_key(monkeypatch):
    monkeypatch.setattr(settings, "HF_TOKEN", None, raising=False)
    monkeypatch.setattr(settings, "HF_API_KEY", None, raising=False)
    monkeypatch.setattr(settings, "HUGGING_FACE_TOKEN", None, raising=False)
    out = await CreativeEngine().generate_video("a cat")
    assert out["success"] is False and "HF_TOKEN" in out["error"]


async def test_space_returns_bytes():
    with patch(
        "apps.core.tools.huggingface_suite.HuggingFaceSuite.generate_video_space",
        new=AsyncMock(return_value={"success": True, "video_bytes": b"MP4DATA"}),
    ):
        out = await CreativeEngine().generate_video("a launch reel")
    assert out["success"] is True
    assert out["video_bytes"] == b"MP4DATA"
    assert out["video_base64"] and out["content_type"] == "video/mp4"


async def test_space_returns_url_downloads_bytes():
    eng = CreativeEngine()
    resp = MagicMock(status_code=200, content=b"DOWNLOADED")
    with patch(
        "apps.core.tools.huggingface_suite.HuggingFaceSuite.generate_video_space",
        new=AsyncMock(return_value={"success": True, "video_url": "https://x/v.mp4"}),
    ), patch.object(eng._http, "get", new=AsyncMock(return_value=resp)):
        out = await eng.generate_video("a reel")
    assert out["success"] is True and out["video_bytes"] == b"DOWNLOADED"


async def test_space_url_download_fails_falls_back_to_url():
    eng = CreativeEngine()
    resp = MagicMock(status_code=500, content=b"")
    with patch(
        "apps.core.tools.huggingface_suite.HuggingFaceSuite.generate_video_space",
        new=AsyncMock(return_value={"success": True, "video_url": "https://x/v.mp4"}),
    ), patch.object(eng._http, "get", new=AsyncMock(return_value=resp)):
        out = await eng.generate_video("a reel")
    assert out["success"] is True and out["video_url"] == "https://x/v.mp4"
    assert "video_bytes" not in out


async def test_space_failure_propagates_error():
    with patch(
        "apps.core.tools.huggingface_suite.HuggingFaceSuite.generate_video_space",
        new=AsyncMock(return_value={"success": False, "error": "Sin video (ZeroGPU puede tener cola)"}),
    ):
        out = await CreativeEngine().generate_video("a reel")
    assert out["success"] is False and "ZeroGPU" in out["error"]
