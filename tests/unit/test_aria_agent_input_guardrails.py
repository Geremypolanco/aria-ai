"""Regression/feature test: AriaAgent.run() (the ReAct loop entry point,
invoked from aria_mind.py's autonomous_execution branch) never checked
Layer 1 (input moderation) or Layer 4 (kill switch) itself — it relied
entirely on its one current caller, aria_mind.py's handle(), having already
run those checks on the raw text earlier in the same turn. That's true
today only by coincidence of handle()'s structure, the same "currently
non-exploitable only by accident" pattern already flagged for the owner-only
tool gate in this same file (test_aria_agent_owner_gate.py) — a future
caller that instantiates AriaAgent directly, bypassing handle(), would
silently skip both layers. run() now checks both itself, respecting
GUARDRAILS_ENABLED like every other layer in this codebase.

Layers 2/3 (constitutional review, content/code firewall) are deliberately
NOT covered here: _execute_tool()'s dispatch has no real mapping for any
consequential tool yet (every pre-registered tool_registry entry lacks a
run() method, so only the hardcoded web_search case ever executes) —
wiring review against tool names nothing can currently reach would be
speculative dead code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_agent import AriaAgent
from apps.core.safety.guardrails import ModerationResult

pytestmark = pytest.mark.asyncio


async def test_run_blocked_when_kill_switch_active():
    agent = AriaAgent()
    fake_switch = AsyncMock()
    fake_switch.is_active = AsyncMock(return_value=True)

    with patch("apps.core.safety.guardrails.get_kill_switch", return_value=fake_switch):
        result = await agent.run("do something", email="frozen@example.com")

    # The account context must actually reach the guard, not just get
    # silently dropped — assert the awaited argument, not merely the result.
    fake_switch.is_active.assert_awaited_once_with("frozen@example.com")
    assert result["success"] is False
    assert result["guardrail_blocked"] is True
    assert "frozen" in result["error"].lower()


async def test_run_blocked_when_input_moderation_flags_the_task():
    agent = AriaAgent()
    fake_switch = AsyncMock()
    fake_switch.is_active = AsyncMock(return_value=False)
    blocked = ModerationResult(blocked=True, categories=["fraud"], confidence=0.9, layer="keyword")

    with (
        patch("apps.core.safety.guardrails.get_kill_switch", return_value=fake_switch),
        patch(
            "apps.core.safety.guardrails.moderate_input", AsyncMock(return_value=blocked)
        ) as mock_moderate,
    ):
        result = await agent.run("set up a ponzi scheme", email="user@example.com")

    fake_switch.is_active.assert_awaited_once_with("user@example.com")
    mock_moderate.assert_awaited_once_with("set up a ponzi scheme", email="user@example.com")
    assert result["success"] is False
    assert result["guardrail_blocked"] is True
    assert "fraud" in result["error"].lower()


async def test_run_proceeds_normally_when_guardrails_clear():
    agent = AriaAgent()
    agent.ai = AsyncMock()
    agent.ai.complete_json = AsyncMock(return_value={"tool": None, "reply": "done"})
    fake_switch = AsyncMock()
    fake_switch.is_active = AsyncMock(return_value=False)
    clear = ModerationResult(blocked=False, layer="none")

    with (
        patch("apps.core.safety.guardrails.get_kill_switch", return_value=fake_switch),
        patch("apps.core.safety.guardrails.moderate_input", AsyncMock(return_value=clear)),
    ):
        result = await agent.run("research the best CRM", email="user@example.com")

    assert result["success"] is True
    assert result["output"] == "done"


async def test_run_skips_guardrail_calls_when_disabled(monkeypatch):
    """GUARDRAILS_ENABLED is the owner's debugging escape hatch (matches
    every other layer's behavior under this flag) — never a production
    bypass, but must actually skip the calls when set."""
    from apps.core.config import settings

    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", False, raising=False)

    agent = AriaAgent()
    agent.ai = AsyncMock()
    agent.ai.complete_json = AsyncMock(return_value={"tool": None, "reply": "done"})

    with patch(
        "apps.core.safety.guardrails.get_kill_switch",
        side_effect=AssertionError("must not be called when guardrails are disabled"),
    ):
        result = await agent.run("research the best CRM", email="user@example.com")

    assert result["success"] is True
