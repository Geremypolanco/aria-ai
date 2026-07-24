"""Regression test: WorkflowEngine.run() hardcoded "success": True in its
return dict regardless of whether any/all steps actually failed — the exact
same bug pattern found and fixed in crew_engine.py. Real consequence: the
REST endpoint at apps/core/routes/api.py (POST /workflows/{id}/run) returns
this dict directly, so a caller checking result["success"] would see True
even when every step raised an exception.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.workflow_engine import Workflow, WorkflowEngine, WorkflowStep

pytestmark = pytest.mark.asyncio


async def test_run_reports_failure_when_all_steps_error():
    engine = WorkflowEngine()
    engine._loaded = True
    wf = Workflow(
        id="wf1",
        name="Test",
        description="desc",
        steps=[WorkflowStep(tool="web_search", args={"query": "x"})],
    )
    engine._workflows["wf1"] = wf

    with patch(
        "apps.core.cognition.aria_mind.get_aria_mind",
    ) as mock_get_mind, patch.object(WorkflowEngine, "_persist", AsyncMock()):
        mock_mind = AsyncMock()
        mock_mind._execute_tool = AsyncMock(side_effect=RuntimeError("tool broke"))
        mock_get_mind.return_value = mock_mind
        result = await engine.run("wf1")

    assert result["success"] is False
    assert result["results"][0]["success"] is False


async def test_run_reports_success_when_all_steps_succeed():
    engine = WorkflowEngine()
    engine._loaded = True
    wf = Workflow(
        id="wf2",
        name="Test",
        description="desc",
        steps=[WorkflowStep(tool="web_search", args={"query": "x"})],
    )
    engine._workflows["wf2"] = wf

    with patch(
        "apps.core.cognition.aria_mind.get_aria_mind",
    ) as mock_get_mind, patch.object(WorkflowEngine, "_persist", AsyncMock()):
        mock_mind = AsyncMock()
        mock_mind._execute_tool = AsyncMock(return_value=("some result", {}))
        mock_get_mind.return_value = mock_mind
        result = await engine.run("wf2")

    assert result["success"] is True
