"""Regression test: EnhancedDevAgent._generate_code() passed the raw
AIResponse object (not .content) to _extract_code(), which calls
re.findall(pattern, response, ...) — requiring a str. This raised
TypeError("expected string or bytes-like object") on every single call,
caught by the surrounding except Exception and always returning
{"success": False, "error": "..."}, so code generation never actually
returned generated code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.agents.enhanced_dev_agent import EnhancedDevAgent
from apps.core.tools.ai_client import AIProvider, AIResponse

pytestmark = pytest.mark.asyncio


async def test_generate_code_extracts_real_code_from_ai_response():
    agent = EnhancedDevAgent.__new__(EnhancedDevAgent)
    fake = AIResponse(
        content="```python\nprint('hello world')\n```",
        provider=AIProvider.GROQ,
        model="x",
        success=True,
    )
    with patch("apps.core.agents.enhanced_dev_agent.get_ai_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(return_value=fake)
        mock_get.return_value = mock_client
        result = await agent._generate_code("write hello world", "python", {})

    assert result["success"] is True
    assert "print('hello world')" in result["code"]


async def test_generate_code_reports_ai_failure_cleanly():
    agent = EnhancedDevAgent.__new__(EnhancedDevAgent)
    fake = AIResponse(
        content="", provider=AIProvider.GROQ, model="x", success=False, error="provider down"
    )
    with patch("apps.core.agents.enhanced_dev_agent.get_ai_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(return_value=fake)
        mock_get.return_value = mock_client
        result = await agent._generate_code("write hello world", "python", {})

    assert result["success"] is False
    assert "provider down" in result["error"]
