"""Regression test: CrewEngine.run()/run_custom() hardcoded run.success = True
unconditionally, even when every crew member's hub.dispatch() call raised an
exception. CrewRun.error was declared in the dataclass but never populated
anywhere. This meant a fully-failed crew run (e.g. BusinessHub down) reported
success: True with no error — a fake success signal in list_runs()/summary().

Also covers a second instance of the same bug class: hub.dispatch() can
return a {"success": False, "error": ...} dict WITHOUT raising (e.g. agent
not found, or BaseAgent.run()'s own circuit-breaker/failure path) — the
original fix only inspected whether dispatch() raised, still treating a
cleanly-returned failure dict as any_success = True.
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


async def test_run_reports_failure_when_dispatch_returns_failure_dict_without_raising():
    """hub.dispatch() legitimately returns {"success": False, ...} on agent-not-found
    or a circuit-breaker/failure path inside BaseAgent.run() — no exception raised."""
    engine = CrewEngine()
    with patch(
        "apps.core.agents.business_hub.BusinessHub.dispatch",
        AsyncMock(return_value={"success": False, "error": "circuit breaker open"}),
    ), patch.object(CrewEngine, "_synthesize", AsyncMock(return_value="synthesized")):
        run = await engine.run("mission", crew_name="research_crew")
    assert run.success is False
    assert run.error is not None
    assert "circuit breaker open" in run.error


async def test_run_custom_reports_failure_when_dispatch_returns_failure_dict_without_raising():
    engine = CrewEngine()
    with patch(
        "apps.core.agents.business_hub.BusinessHub.dispatch",
        AsyncMock(return_value={"success": False, "error": "circuit breaker open"}),
    ), patch.object(CrewEngine, "_synthesize", AsyncMock(return_value="synthesized")):
        run = await engine.run_custom("mission", roles=["researcher", "developer"])
    assert run.success is False
    assert run.error is not None
    assert "circuit breaker open" in run.error
