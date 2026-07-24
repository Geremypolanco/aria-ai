"""Regression test: MultimodalEngine.analyze_image() called
AriaAIClient.analyze_image() with a media_type= kwarg that doesn't exist
on the real method (apps/core/tools/ai_client.py:705 only accepts
image_base64 and question). This raised TypeError on every invocation,
caught by the surrounding bare except and turned into a generic
{"success": False, "error": "...unexpected keyword argument..."} —
meaning every entry point built on top of analyze_image (extract_text,
analyze_chart, analyze_document, sketch_to_description, image_to_prompt,
and the video frame-analysis loop) was permanently broken.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.tools.multimodal import MultimodalEngine

pytestmark = pytest.mark.asyncio


async def test_analyze_image_calls_ai_client_with_only_valid_kwargs():
    engine = MultimodalEngine()
    fake_client = MagicMock()
    fake_client.analyze_image = AsyncMock(return_value="a description")

    with patch("apps.core.tools.ai_client.get_ai_client", return_value=fake_client):
        result = await engine.analyze_image(image_bytes=b"\xff\xd8fakejpegdata", question="What is this?")

    assert result["success"] is True
    fake_client.analyze_image.assert_awaited_once()
    _, kwargs = fake_client.analyze_image.call_args
    assert set(kwargs.keys()) == {"image_base64", "question"}
