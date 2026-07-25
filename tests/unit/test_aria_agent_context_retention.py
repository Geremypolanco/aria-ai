"""Regression test: AriaAgent's ReAct loop (_think()) only passed
self.history[-1]["content"] to the LLM — the single most recent entry. From
step 2 onward that's just the latest tool observation; the original task
(self.history[0]) was never sent again, and complete_json()/complete() only
take flat system/user strings (no message-list parameter), so there was no
other way for the model to see it. A multi-step run would genuinely lose
track of what it was trying to accomplish partway through. _think() now
sends the full transcript (original task + every thought/action/observation
since) as the user string.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.core.cognition.aria_agent import AriaAgent

pytestmark = pytest.mark.asyncio


async def test_think_includes_the_original_task_from_step_two_onward():
    agent = AriaAgent()
    agent.ai = AsyncMock()
    agent.ai.complete_json = AsyncMock(return_value={"tool": None, "reply": "done"})

    agent.history = [
        {"role": "user", "content": "Research the best CRM for a 5-person startup"},
        {
            "role": "assistant",
            "content": '{"thought": "searching", "tool": "web_search", "tool_args": {}}',
        },
        {"role": "user", "content": "OBSERVATION from web_search: [some results]"},
    ]

    await agent._think()

    sent_user = agent.ai.complete_json.call_args.kwargs["user"]
    assert "Research the best CRM for a 5-person startup" in sent_user
    assert "OBSERVATION from web_search" in sent_user


async def test_think_still_works_on_the_first_step():
    agent = AriaAgent()
    agent.ai = AsyncMock()
    agent.ai.complete_json = AsyncMock(return_value={"tool": None, "reply": "done"})
    agent.history = [{"role": "user", "content": "Do the thing"}]

    await agent._think()

    sent_user = agent.ai.complete_json.call_args.kwargs["user"]
    assert "Do the thing" in sent_user
