"""Regression test: summarize(), analyze_sentiment(), describe_image(), and
translate() indexed result["result"][0] without checking the list was
non-empty first — inconsistent with detect_language() and classify_text() in
the same file, which correctly guard with `if result["result"]:` before
indexing. An empty list response (a real possibility for empty/degenerate
input) raised an uncaught IndexError in the unguarded methods, reachable
directly from ContentAgent (apps/core/agents/content_agent.py). translate()
was the one sibling missed by the original fix to this bug class.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.hf_discovery import HFDiscovery

pytestmark = pytest.mark.asyncio


async def test_summarize_handles_empty_result_list():
    hf = HFDiscovery()
    with patch.object(
        HFDiscovery, "discover_and_run", AsyncMock(return_value={"success": True, "result": []})
    ):
        result = await hf.summarize("some text")
    assert "summary" not in result


async def test_analyze_sentiment_handles_empty_result_list():
    hf = HFDiscovery()
    with patch.object(
        HFDiscovery, "discover_and_run", AsyncMock(return_value={"success": True, "result": []})
    ):
        result = await hf.analyze_sentiment("some text")
    assert "label" not in result


async def test_describe_image_handles_empty_result_list():
    hf = HFDiscovery()
    with patch.object(
        HFDiscovery, "discover_and_run", AsyncMock(return_value={"success": True, "result": []})
    ):
        result = await hf.describe_image(b"fake image bytes")
    assert "caption" not in result


async def test_translate_handles_empty_result_list():
    hf = HFDiscovery()
    with patch.object(
        HFDiscovery, "_run_model", AsyncMock(return_value={"success": True, "result": []})
    ):
        result = await hf.translate("hello")
    assert "translation" not in result
