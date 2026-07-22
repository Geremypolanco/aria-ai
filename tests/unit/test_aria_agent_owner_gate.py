"""Regression test: AriaAgent's autonomous-execution path could reach
GitHubTool/DockerTool/DeploymentTool (subprocess-shelling, real GitHub API
writes) with no owner check. Currently non-exploitable only by accident (no
GITHUB_TOKEN wired in, no docker/vercel CLI in the container) — gated
properly now instead of relying on that."""

from __future__ import annotations

import pytest

from apps.core.cognition.aria_agent import AriaAgent

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("tool", ["github", "docker", "deployment"])
async def test_dangerous_tools_rejected_for_non_owner(tool):
    agent = AriaAgent(is_owner=False)
    result = await agent._execute_tool(tool, {})
    assert "error" in result
    assert "reservada al dueño" in result["error"]


async def test_web_search_remains_open_for_non_owner():
    agent = AriaAgent(is_owner=False)
    # Not asserting success (no network in tests) — just that it isn't
    # rejected by the owner gate before even trying.
    result = await agent._execute_tool("web_search", {"query": "test"})
    assert "reservada al dueño" not in str(result.get("error", ""))
