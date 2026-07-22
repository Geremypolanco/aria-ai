"""Regression test: TaskExecutor previously hardcoded "success": True
regardless of whether agent.think()/generate_code()/research() actually
succeeded — those methods never raise, they encode failure as a "⚠️ ..."
string instead, so success must be derived from the content."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.execution_engine import TaskExecutor

pytestmark = pytest.mark.asyncio


async def test_execute_reports_failure_when_ai_unavailable():
    agent = AsyncMock()
    agent.think = AsyncMock(
        side_effect=[
            "⚠️ **ARIA no está completamente inicializada**",  # understanding
            "⚠️ **ARIA no está completamente inicializada**",  # result
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
    agent.generate_code = AsyncMock(return_value="⚠️ Todos los proveedores de IA fallaron.")
    with patch("apps.core.execution_engine.get_agent", return_value=agent):
        result = await TaskExecutor().execute_code("write a function")
    assert result["success"] is False
