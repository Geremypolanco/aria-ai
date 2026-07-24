"""Regression test: three methods in presentation_builder.py passed the raw
AIResponse object (returned by ai_client.AriaAIClient.complete()) directly to
string-processing code instead of unwrapping .content:

1. _generate_outline() did resp.split("\n") — AIResponse has no .split(),
   so this raised AttributeError uncaught, crashing create_presentation()
   on every single call (verified live).
2. _generate_slides()'s gen_slide() passed resp (not resp.content) to
   _parse_single_slide(), which calls text.strip() — this also raised
   AttributeError, but was silently swallowed by
   asyncio.gather(..., return_exceptions=True), so every AI-generated slide
   silently degraded to a bare {"title": ...} with no bullets/subtitle.
3. create_pitch_deck() passed the raw AIResponse to _parse_slides_json(),
   which wraps text.strip() in a bare try/except — so it always silently
   fell back to the static _default_pitch_deck() template, and the
   AI-tailored 10-slide deck was never actually used.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.ai_client import AIProvider, AIResponse
from apps.core.tools.presentation_builder import PresentationBuilder

pytestmark = pytest.mark.asyncio


def _fake_response(content: str) -> AIResponse:
    return AIResponse(content=content, provider=AIProvider.GROQ, model="x", success=True)


async def test_generate_outline_does_not_crash_on_ai_response():
    pb = PresentationBuilder()
    fake = _fake_response("1. Intro\n2. Problem\n3. Solution")
    with patch("apps.core.tools.ai_client.get_ai_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(return_value=fake)
        mock_get.return_value = mock_client
        outline = await pb._generate_outline("Title", "Topic", 3)
    assert outline == ["Intro", "Problem", "Solution"]


async def test_generate_slides_uses_real_ai_generated_content():
    pb = PresentationBuilder()
    fake = _fake_response('{"title": "T", "subtitle": "S", "bullets": ["a", "b"]}')
    with patch("apps.core.tools.ai_client.get_ai_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(return_value=fake)
        mock_get.return_value = mock_client
        slides = await pb._generate_slides("Title", "Topic", ["Slide A"])
    assert slides[0]["subtitle"] == "S"
    assert slides[0]["bullets"] == ["a", "b"]


async def test_create_pitch_deck_uses_ai_generated_slides_not_default():
    pb = PresentationBuilder()
    ai_slides = [{"title": "Custom AI Slide", "bullets": ["unique content"]}]
    import json

    fake = _fake_response(json.dumps(ai_slides))
    with patch("apps.core.tools.ai_client.get_ai_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(return_value=fake)
        mock_get.return_value = mock_client
        result = await pb.create_pitch_deck("Acme", "problem", "solution")
    assert result["slide_count"] == 1
    assert b"Custom AI Slide" in result["html_bytes"]
