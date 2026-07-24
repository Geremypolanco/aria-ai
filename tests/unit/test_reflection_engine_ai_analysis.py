"""Regression test: ReflectionEngine._analyze_and_decide() called
client.complete(prompt, model=..., max_tokens=...) — but AriaAIClient.complete()
requires both `system` and `user` as positional/keyword args with no default
for `user`. This raised TypeError on every single call (verified live), so
the AI-powered reflection analysis has never actually run — it always fell
back to the crude rule-based branch that only looks at weak_skills and
ignores issues/error_patterns entirely.

Also fixed: `if response:` is always truthy for an AIResponse dataclass
(no __bool__), and `response.split(...)` was called on the AIResponse object
itself rather than `response.content`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.reflection_engine import ReflectionEngine
from apps.core.tools.ai_client import AIProvider, AIResponse

pytestmark = pytest.mark.asyncio


async def test_analyze_and_decide_uses_real_ai_response_not_just_fallback():
    engine = ReflectionEngine()
    evidence = {"issues": ["deploy failed 3x"], "weak_skills": ["coding"], "error_patterns": []}
    fake = AIResponse(
        content=(
            "DECISION: refactor the deploy pipeline\n"
            "PRIORITY: high\n"
            "TARGET: deployment\n"
            "REASON: repeated failures\n"
            "---"
        ),
        provider=AIProvider.GROQ,
        model="x",
        success=True,
    )
    with patch("apps.core.tools.ai_client.get_ai_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(return_value=fake)
        mock_get.return_value = mock_client
        decisions = await engine._analyze_and_decide(evidence)

    mock_client.complete.assert_awaited_once()
    _, kwargs = mock_client.complete.call_args
    assert "user" in kwargs and "system" in kwargs
    assert decisions == [
        {
            "decision": "refactor the deploy pipeline",
            "priority": "high",
            "target": "deployment",
            "reason": "repeated failures",
            "created_at": decisions[0]["created_at"],
            "applied": False,
        }
    ]


async def test_analyze_and_decide_falls_back_when_ai_unavailable():
    engine = ReflectionEngine()
    evidence = {"issues": [], "weak_skills": ["coding"], "error_patterns": []}
    with patch("apps.core.tools.ai_client.get_ai_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(side_effect=RuntimeError("provider down"))
        mock_get.return_value = mock_client
        decisions = await engine._analyze_and_decide(evidence)

    assert decisions
    assert decisions[0]["target"] == "coding"
