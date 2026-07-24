"""Regression tests for two bugs found while auditing run_business_agent:

1. BusinessHub.dispatch() called agent.execute(context) — no agent class
   anywhere defines `execute`; the real public entry point is
   BaseAgent.run(). Every single dispatch, for every one of the 11
   registered agent aliases, has always raised AttributeError (caught and
   turned into a generic failure result, so it never crashed a request,
   but the *capability* has never worked at all).
2. Once dispatch actually reaches DeveloperAgent, it defaults to
   auto_run=True and executes generated code via CodeRunner (no real
   sandbox) — must be owner-gated, same as the direct execute_code tool.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from apps.core.agents.business_hub import BusinessHub

pytestmark = pytest.mark.asyncio


async def test_dispatch_actually_calls_run_not_execute():
    """Would previously fail every time with AttributeError."""
    result = await BusinessHub().dispatch("marketing", "write a tagline", {})
    assert "object has no attribute 'execute'" not in str(result.get("error", ""))


async def test_developer_agent_skips_execution_for_non_owner():
    result = await BusinessHub().dispatch(
        "developer", "write a hello world function", {"is_owner": False}
    )
    assert result.get("execution_skipped")
    assert "execution" not in result or not result.get("execution", {}).get("success")


async def test_developer_agent_runs_code_for_owner():
    async def fake_generate_code(*a, **k):
        return "print('hi')"

    async def fake_design(*a, **k):
        return "trivial"

    async def fake_tests(*a, **k):
        return ""

    with patch(
        "apps.core.agents.business.developer_agent.DeveloperAgent._generate_code",
        fake_generate_code,
    ), patch(
        "apps.core.agents.business.developer_agent.DeveloperAgent._design_solution", fake_design
    ), patch(
        "apps.core.agents.business.developer_agent.DeveloperAgent._generate_tests", fake_tests
    ):
        result = await BusinessHub().dispatch(
            "developer", "print hi", {"is_owner": True, "auto_fix": False}
        )
    assert "execution" in result
    assert result["execution"]["success"] is True
    assert "hi" in result["execution"]["output"]
