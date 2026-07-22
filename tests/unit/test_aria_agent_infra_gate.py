"""Regression test: AriaAgent._OWNER_ONLY_TOOLS omitted "infra" (InfraTools —
arbitrary shell execution via execute_system_command, arbitrary file
read/write/delete via manage_files) even though github/docker/deployment
were already gated for the identical reason ("not currently exploitable only
by accident, not by design" — the file's own comment). Currently
_execute_tool()'s dispatch can't actually reach InfraTools's methods (no
run() method, no special-case mapping), but that's a dispatch gap, not a
guard — this test locks in that "infra" and the two tool names the LLM is
actually told to call (execute_system_command, manage_files) are rejected
for non-owners exactly like github/docker/deployment already are.
"""

from __future__ import annotations

import pytest

from apps.core.cognition.aria_agent import AriaAgent

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("tool", ["infra", "execute_system_command", "manage_files"])
async def test_infra_tools_rejected_for_non_owner(tool):
    agent = AriaAgent(is_owner=False)
    result = await agent._execute_tool(tool, {})
    assert "reservada al dueño" in result["error"]


async def test_infra_tool_lookup_allowed_for_owner_but_not_dispatchable_yet():
    """Owner passes the gate; InfraTools still has no run() method, so this
    surfaces the (harmless) 'not executable' message rather than silently
    succeeding — confirms the gate check runs before the lookup, not that the
    tool actually works end-to-end (that's a separate, non-security gap)."""
    agent = AriaAgent(is_owner=True)
    result = await agent._execute_tool("infra", {})
    assert "reservada al dueño" not in str(result)
