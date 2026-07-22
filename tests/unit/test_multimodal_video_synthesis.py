"""Regression test: MultimodalEngine.analyze_video_bytes() never unwrapped
the AIResponse returned by client.complete() for its synthesis step —
"analysis": synthesis stored the raw dataclass object, and never checked
.success. Consumed by aria_mind.py's video-analysis tool via an f-string
(f"...\n{r['analysis']}"), which implicitly stringifies the AIResponse to
its dataclass repr instead of showing the actual synthesized text, and a
failed completion was reported as success: True.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.ai_client import AIProvider, AIResponse
from apps.core.tools.multimodal import MultimodalEngine

pytestmark = pytest.mark.asyncio


async def test_analyze_video_bytes_unwraps_synthesis_content():
    tools = MultimodalEngine()
    fake_synthesis = AIResponse(
        content="El video muestra un producto siendo desempacado.",
        provider=AIProvider.GROQ,
        model="x",
        success=True,
    )
    with patch.object(
        MultimodalEngine,
        "analyze_image",
        AsyncMock(return_value={"success": True, "analysis": "frame description"}),
    ), patch.object(
        MultimodalEngine, "_extract_frames", return_value=[b"frame1", b"frame2"]
    ), patch("apps.core.tools.ai_client.get_ai_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(return_value=fake_synthesis)
        mock_get.return_value = mock_client
        result = await tools.analyze_video_bytes(b"fake video bytes", "What is happening?")

    assert result["success"] is True
    assert result["analysis"] == "El video muestra un producto siendo desempacado."


async def test_analyze_video_bytes_reports_failure_when_synthesis_fails():
    tools = MultimodalEngine()
    fake_synthesis = AIResponse(
        content="", provider=AIProvider.GROQ, model="x", success=False, error="all providers down"
    )
    with patch.object(
        MultimodalEngine,
        "analyze_image",
        AsyncMock(return_value={"success": True, "analysis": "frame description"}),
    ), patch.object(
        MultimodalEngine, "_extract_frames", return_value=[b"frame1"]
    ), patch("apps.core.tools.ai_client.get_ai_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(return_value=fake_synthesis)
        mock_get.return_value = mock_client
        result = await tools.analyze_video_bytes(b"fake video bytes", "What is happening?")

    assert result["success"] is False
    assert "all providers down" in result["error"]
