"""
ARIA AI — Agent Execution Engine.
Connects the AI to real tools and executes tasks with proper chain-of-thought.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from apps.core.agent_brain import get_agent, is_failure_reply
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.execution")


class TaskExecutor:
    """Executes tasks using ARIA's reasoning and tool system."""

    async def execute(self, task: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a task with full reasoning chain."""
        agent = get_agent()
        context = context or {}

        # Phase 1: Understand the task
        understanding = await agent.think(
            f"Analyze this task and break it down into steps:\n\n{task}",
            model=AIModel.STRATEGY,
            temperature=0.3,
        )

        # Phase 2: Determine required tools
        tool_plan = await agent.think_json(
            f"""Given this task: {task}

Which tools are needed?
Respond ONLY with JSON:
{{
  "tools_needed": ["list", "of", "tools"],
  "steps": ["step1", "step2"],
  "estimated_complexity": "low/medium/high"
}}""",
        )

        # Phase 3: Execute (simplified - in production this would call real tools)
        result = await agent.think(
            f"Execute this task:\n\n{task}\n\nContext: {json.dumps(context, ensure_ascii=False)}",
            model=AIModel.STRATEGY,
            temperature=0.5,
            max_tokens=8192,
        )

        # agent.think() never raises — it swallows provider/config failures into
        # one of a few fixed reply strings instead, so "success" must actually
        # check for those rather than being hardcoded True regardless of outcome.
        succeeded = not (isinstance(result, str) and is_failure_reply(result))
        return {
            "success": succeeded,
            "task": task,
            "understanding": understanding,
            "tool_plan": tool_plan,
            "result": result,
        }

    async def execute_code(self, prompt: str, language: str = "python") -> dict[str, Any]:
        """Execute a code generation task."""
        agent = get_agent()
        code = await agent.generate_code(prompt, language)
        succeeded = not (isinstance(code, str) and is_failure_reply(code))
        return {"success": succeeded, "code": code, "language": language}

    async def research_topic(self, topic: str) -> dict[str, Any]:
        """Execute a research task."""
        agent = get_agent()
        research = await agent.research(topic)
        succeeded = not (isinstance(research, str) and is_failure_reply(research))
        return {"success": succeeded, "topic": topic, "research": research}


# ── SINGLETON ─────────────────────────────────────────────
_executor: TaskExecutor | None = None


def get_executor() -> TaskExecutor:
    global _executor
    if _executor is None:
        _executor = TaskExecutor()
    return _executor
