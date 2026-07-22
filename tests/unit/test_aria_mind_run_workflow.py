"""Regression test: the "run_workflow" chat tool used to branch on
r.get("success") to decide whether to show the per-step OK/FAIL breakdown —
once workflow_engine.run() was fixed to report success truthfully (instead
of always True), that branch would have started hiding the useful per-step
summary behind a generic "Error ejecutando workflow: error" message whenever
any step failed. The handler must show the breakdown regardless of overall
success, only varying the header.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind

pytestmark = pytest.mark.asyncio


async def test_run_workflow_shows_step_breakdown_even_on_partial_failure():
    fake_result = {
        "success": False,
        "workflow_id": "wf1",
        "name": "Test WF",
        "steps_run": 2,
        "results": [
            {"step": 1, "tool": "web_search", "desc": "", "success": True, "output": "ok"},
            {"step": 2, "tool": "execute_code", "desc": "", "success": False, "error": "boom"},
        ],
        "final_output": "ok",
    }
    with patch(
        "apps.core.tools.workflow_engine.get_workflow_engine",
    ) as mock_get_engine:
        mock_engine = AsyncMock()
        mock_engine.run = AsyncMock(return_value=fake_result)
        mock_get_engine.return_value = mock_engine

        mind = AriaMind()
        obs, _ = await mind._execute_tool("run_workflow", {"workflow_id": "wf1"})

    assert "paso1=OK" in obs
    assert "paso2=FAIL" in obs


async def test_run_workflow_still_reports_hard_error_for_missing_workflow():
    fake_result = {"success": False, "error": "Workflow 'wf1' no encontrado"}
    with patch(
        "apps.core.tools.workflow_engine.get_workflow_engine",
    ) as mock_get_engine:
        mock_engine = AsyncMock()
        mock_engine.run = AsyncMock(return_value=fake_result)
        mock_get_engine.return_value = mock_engine

        mind = AriaMind()
        obs, _ = await mind._execute_tool("run_workflow", {"workflow_id": "wf1"})

    assert "no encontrado" in obs
