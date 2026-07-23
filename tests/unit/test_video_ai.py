"""
Tests for the layer-2 AI video provider (apps/core/tools/video_ai.py). The real
GPU calls can't run without a token; here we lock the orchestration: availability
gate, Replicate success (poll → output → download), fal.ai fallback when
Replicate errors, and a clean error when nothing is configured.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.config import settings
from apps.core.tools.video_ai import AIVideoProvider


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.setattr(settings, "REPLICATE_API_TOKEN", None, raising=False)
    monkeypatch.setattr(settings, "FAL_KEY", None, raising=False)
    yield


def _client_cm(post_resp, get_resps):
    """Build an async-context-manager httpx client mock."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=post_resp)
    client.get = AsyncMock(side_effect=get_resps)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def test_not_available_without_tokens():
    assert AIVideoProvider().available() is False


async def test_no_provider_returns_error():
    out = await AIVideoProvider().generate("a dog")
    assert out["success"] is False and "No AI video provider" in out["error"]


async def test_replicate_succeeds_and_downloads(monkeypatch):
    monkeypatch.setattr(settings, "REPLICATE_API_TOKEN", "r8_x", raising=False)
    post = MagicMock(status_code=201)
    post.json.return_value = {"status": "succeeded", "output": "https://x/v.mp4", "urls": {"get": "https://x/g"}}
    dl = MagicMock(status_code=200, content=b"MP4")
    with patch("httpx.AsyncClient", return_value=_client_cm(post, [dl])):
        out = await AIVideoProvider().generate("a neon city")
    assert out["success"] is True
    assert out["video_bytes"] == b"MP4" and out["provider"] == "replicate"


async def test_replicate_polls_until_succeeded(monkeypatch):
    monkeypatch.setattr(settings, "REPLICATE_API_TOKEN", "r8_x", raising=False)
    post = MagicMock(status_code=201)
    post.json.return_value = {"status": "processing", "urls": {"get": "https://x/g"}}
    poll = MagicMock(status_code=200)
    poll.json.return_value = {"status": "succeeded", "output": ["https://x/v.mp4"]}
    dl = MagicMock(status_code=200, content=b"VID")
    with patch("apps.core.tools.video_ai.asyncio.sleep", new=AsyncMock()), patch(
        "httpx.AsyncClient", return_value=_client_cm(post, [poll, dl])
    ):
        out = await AIVideoProvider().generate("a dragon")
    assert out["success"] is True and out["video_bytes"] == b"VID"


async def test_fal_fallback_when_replicate_fails(monkeypatch):
    monkeypatch.setattr(settings, "REPLICATE_API_TOKEN", "r8_x", raising=False)
    monkeypatch.setattr(settings, "FAL_KEY", "fal_x", raising=False)
    rep_post = MagicMock(status_code=500, text="boom")
    fal_post = MagicMock(status_code=200)
    fal_post.json.return_value = {"video": {"url": "https://f/v.mp4"}}
    dl = MagicMock(status_code=200, content=b"FALMP4")

    calls = {"n": 0}

    def make_client(*a, **k):
        calls["n"] += 1
        return _client_cm(rep_post, []) if calls["n"] == 1 else _client_cm(fal_post, [dl])

    with patch("httpx.AsyncClient", side_effect=make_client):
        out = await AIVideoProvider().generate("a wave")
    assert out["success"] is True and out["provider"] == "fal" and out["video_bytes"] == b"FALMP4"
