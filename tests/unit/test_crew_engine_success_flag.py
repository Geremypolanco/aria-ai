"""Regression test: CrewEngine.run()/run_custom() hardcoded run.success = True
unconditionally, even when every crew member's hub.dispatch() call raised an
exception. CrewRun.error was declared in the dataclass but never populated
anywhere. This meant a fully-failed crew run (e.g. BusinessHub down) reported
success: True with no error — a fake success signal in list_runs()/summary().
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.crew_engine import CrewEngine

pytestmark = pytest.mark.asyncio


async def test_run_reports_failure_when_all_members_error():
    engine = CrewEngine()
    with patch(
        "apps.core.agents.business_hub.BusinessHub.dispatch",
        AsyncMock(side_effect=RuntimeError("agent dispatch broken")),
    ), patch.object(CrewEngine, "_synthesize", AsyncMock(return_value="synthesized")):
        run = await engine.run("mission", crew_name="research_crew")
    assert run.success is False
    assert run.error is not None
    assert "agent dispatch broken" in run.error


async def test_run_reports_success_when_at_least_one_member_succeeds():
    engine = CrewEngine()

    async def fake_dispatch(agent_type, prompt, context):
        if agent_type == "research":
            return {"output": "real research findings"}
        raise RuntimeError("boom")

    with patch(
        "apps.core.agents.business_hub.BusinessHub.dispatch", AsyncMock(side_effect=fake_dispatch)
    ), patch.object(CrewEngine, "_synthesize", AsyncMock(return_value="synthesized")):
        run = await engine.run("mission", crew_name="research_crew")
    assert run.success is True
    assert run.error is None


async def test_run_custom_reports_failure_when_all_members_error():
    engine = CrewEngine()
    with patch(
        "apps.core.agents.business_hub.BusinessHub.dispatch",
        AsyncMock(side_effect=RuntimeError("agent dispatch broken")),
    ), patch.object(CrewEngine, "_synthesize", AsyncMock(return_value="synthesized")):
        run = await engine.run_custom("mission", roles=["researcher", "developer"])
    assert run.success is False
    assert run.error is not None
