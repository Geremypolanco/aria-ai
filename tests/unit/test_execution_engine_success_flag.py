"""Regression test: TaskExecutor previously hardcoded "success": True
regardless of whether agent.think()/generate_code()/research() actually
succeeded — those methods never raise, they encode failure as one of a few
fixed reply strings instead, so success must be derived from the content.

Also covers a second-order regression: an earlier version of this test (and
of agent_brain.py's replies) used a "⚠️ ..." emoji prefix as the failure
marker. Two independent translation passes on agent_brain.py dropped that
prefix from the actual reply text without updating this check, silently
turning every failure into a reported "success". is_failure_reply() is now
the one shared place that contract lives, so this test exercises the real
current strings via that helper instead of a hardcoded prefix that no longer
appears in production output."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.agent_brain import ALL_PROVIDERS_FAILED_REPLY, NO_PROVIDER_REPLY
from apps.core.execution_engine import TaskExecutor

pytestmark = pytest.mark.asyncio


async def test_execute_reports_failure_when_ai_unavailable():
    agent = AsyncMock()
    agent.think = AsyncMock(
        side_effect=[
            NO_PROVIDER_REPLY,  # understanding
            NO_PROVIDER_REPLY,  # result
        ]
    )
    agent.think_json = AsyncMock(return_value={"tools_needed": []})
    with patch("apps.core.execution_engine.get_agent", return_value=agent):
        result = await TaskExecutor().execute("do something")
    assert result["success"] is False


async def test_execute_reports_success_on_real_content():
    agent = AsyncMock()
    agent.think = AsyncMock(side_effect=["Plan: step 1, step 2", "Done: report here"])
    agent.think_json = AsyncMock(return_value={"tools_needed": []})
    with patch("apps.core.execution_engine.get_agent", return_value=agent):
        result = await TaskExecutor().execute("do something")
    assert result["success"] is True


async def test_execute_code_reports_failure_on_provider_error():
    agent = AsyncMock()
    agent.generate_code = AsyncMock(return_value=ALL_PROVIDERS_FAILED_REPLY)
    with patch("apps.core.execution_engine.get_agent", return_value=agent):
        result = await TaskExecutor().execute_code("write a function")
    assert result["success"] is False
