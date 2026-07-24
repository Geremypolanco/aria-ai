"""
Tests for the ffmpeg reel engine (apps/core/tools/video_engine.py) — ARIA's own
layer-1 video generator. The real ffmpeg composition is verified separately; here
we lock the orchestration: no-ffmpeg guard, scene→image→voice flow, the empty
result guard, and the deterministic scene-plan fallback.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.video_engine import VideoEngine


def _ct_mock(image_ok=True, tts_ok=True):
    ct = AsyncMock()
    ct.flux_generate_image = AsyncMock(
        return_value={"success": True, "image_bytes": b"PNG"} if image_ok else {"success": False}
    )
    ct.elevenlabs_tts = AsyncMock(
        return_value={"success": True, "audio_base64": "YXVkaW8="} if tts_ok else {"success": False}
    )
    return ct


async def test_no_ffmpeg_is_clean_error():
    eng = VideoEngine()
    with patch.object(VideoEngine, "ffmpeg_bin", staticmethod(lambda: None)):
        out = await eng.generate("a dog")
    assert out["success"] is False and "ffmpeg" in out["error"]


async def test_success_path_returns_video_bytes():
    eng = VideoEngine()
    scenes = [{"image_prompt": "p", "caption": "c", "narration": "n"}]
    with patch.object(VideoEngine, "ffmpeg_bin", staticmethod(lambda: "ffmpeg")), patch.object(
        VideoEngine, "_plan", new=AsyncMock(return_value=scenes)
    ), patch(
        "apps.core.tools.content_tools.ContentTools", return_value=_ct_mock()
    ), patch.object(
        VideoEngine, "_compose", return_value=b"MP4BYTES"
    ):
        out = await eng.generate("a dancing dog")
    assert out["success"] is True
    assert out["video_bytes"] == b"MP4BYTES"
    assert out["video_base64"] and out["scenes"] == 1 and out["has_audio"] is True


async def test_no_images_is_clean_error():
    eng = VideoEngine()
    scenes = [{"image_prompt": "p", "caption": "", "narration": ""}]
    with patch.object(VideoEngine, "ffmpeg_bin", staticmethod(lambda: "ffmpeg")), patch.object(
        VideoEngine, "_plan", new=AsyncMock(return_value=scenes)
    ), patch("apps.core.tools.content_tools.ContentTools", return_value=_ct_mock(image_ok=False)):
        out = await eng.generate("a dog")
    assert out["success"] is False and "image" in out["error"]


async def test_plan_fallback_when_ai_unavailable():
    eng = VideoEngine()
    # No AI client patching → get_ai_client will raise/misbehave → deterministic fallback.
    with patch(
        "apps.core.tools.ai_client.get_ai_client", side_effect=RuntimeError("no ai")
    ):
        scenes = await eng._plan("cyberpunk city", 3)
    assert len(scenes) == 3
    assert all("cyberpunk city" in s["image_prompt"] for s in scenes)
