"""Regression test: apps/core/llm/llm_client.py's complete_json() shim
accepted **kwargs but never forwarded them to the underlying
AriaAIClient.complete_json() call. Dozens of call sites throughout
income_loop.py pass an explicit max_tokens= expecting it to matter (e.g.
max_tokens=3000 for a full landing-page HTML generator) — silently dropped,
so every call ran with the hardcoded default (2000), which could truncate
larger JSON responses mid-object and cause them to fail to parse, then get
misreported upstream as "AI failed" when the real cause was a dropped kwarg.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.llm.llm_client import complete_json

pytestmark = pytest.mark.asyncio


async def test_complete_json_forwards_max_tokens_kwarg():
    mock_client = AsyncMock()
    mock_client.complete_json = AsyncMock(return_value={"ok": True})

    with patch("apps.core.tools.ai_client.get_ai_client", return_value=mock_client):
        await complete_json("write something", model="fast", max_tokens=3000, temperature=0.9)

    mock_client.complete_json.assert_awaited_once()
    _, kwargs = mock_client.complete_json.call_args
    assert kwargs["max_tokens"] == 3000
    assert kwargs["temperature"] == 0.9
