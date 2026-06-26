"""
ARIA LangGraph — CognitiveAgent high-level interface.

Wraps the compiled LangGraph workflow with a clean async API.
Falls back to a direct single AI call when LangGraph is not available.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from apps.cognition.langgraph.agent_state import AgentState
from apps.cognition.langgraph.workflow import build_cognitive_workflow
from apps.core.tools.ai_client import get_ai_client

logger = logging.getLogger("aria.cognition.agent")

# Module-level singleton
_cognitive_agent: CognitiveAgent | None = None


class CognitiveAgent:
    """
    High-level cognitive agent backed by a LangGraph StateGraph.

    If LangGraph is not installed, each run() call falls back to a single
    direct AI call so the rest of the codebase always has a working agent.
    """

    def __init__(self, agent_id: str = "", max_iterations: int = 3) -> None:
        self.agent_id: str = agent_id or str(uuid.uuid4())[:8]
        self.max_iterations: int = max(1, max_iterations)
        self._workflow = build_cognitive_workflow()
        self._history: list[dict] = []

        if self._workflow is not None:
            logger.info("[CognitiveAgent %s] LangGraph workflow active", self.agent_id)
        else:
            logger.info("[CognitiveAgent %s] Using fallback (no LangGraph)", self.agent_id)

    # ── public API ────────────────────────────────────────────────────────────

    async def run(self, task: str, context: dict | None = None) -> dict:
        """
        Run a task through the cognitive workflow.

        Returns a result dict with keys:
          task, result, confidence, reasoning_steps, plan, status, iterations
        """
        if context is None:
            context = {}

        if self._workflow is not None:
            result = await self._workflow_run(task, context)
        else:
            result = await self._fallback_run(task, context)

        self._history.append({**result, "ts": time.time()})
        return result

    def history(self) -> list[dict]:
        """Return the last 50 run results."""
        return list(self._history[-50:])

    def summary(self) -> dict:
        """Return aggregate statistics for this agent."""
        total = len(self._history)
        successful = sum(1 for h in self._history if h.get("status") == "done")
        return {
            "agent_id": self.agent_id,
            "total_runs": total,
            "successful": successful,
            "success_rate": successful / total if total else 0.0,
            "langgraph_active": self._workflow is not None,
        }

    # ── internal helpers ──────────────────────────────────────────────────────

    async def _workflow_run(self, task: str, context: dict) -> dict:
        """Invoke the compiled LangGraph workflow in a thread pool."""
        initial_state: AgentState = AgentState(  # type: ignore[call-arg]
            messages=[],
            task=task,
            context=context,
            reasoning_steps=[],
            plan=[],
            current_step=0,
            result="",
            confidence=0.0,
            iteration=0,
            max_iterations=self.max_iterations,
            status="thinking",
        )

        try:
            # workflow.invoke() is synchronous — run in executor
            loop = asyncio.get_event_loop()
            final_state: dict = await loop.run_in_executor(
                None,
                lambda: self._workflow.invoke(initial_state),  # type: ignore[union-attr]
            )
            return {
                "task": task,
                "result": final_state.get("result", ""),
                "confidence": final_state.get("confidence", 0.0),
                "reasoning_steps": final_state.get("reasoning_steps", []),
                "plan": final_state.get("plan", []),
                "status": final_state.get("status", "done"),
                "iterations": final_state.get("iteration", 0),
            }
        except Exception as exc:
            logger.error("[CognitiveAgent %s] workflow run failed: %s", self.agent_id, exc)
            return {
                "task": task,
                "result": "",
                "confidence": 0.0,
                "reasoning_steps": [],
                "plan": [],
                "status": "failed",
                "iterations": 0,
                "error": str(exc),
            }

    async def _fallback_run(self, task: str, context: dict) -> dict:
        """
        Simple AI call fallback when LangGraph is not available.

        Calls get_ai_client() (SYNC) then awaits ai.complete().
        """
        ai = get_ai_client()
        if ai is None:
            return {
                "task": task,
                "result": "AI client unavailable",
                "confidence": 0.0,
                "reasoning_steps": ["No AI client — skipped"],
                "plan": [],
                "status": "failed",
                "iterations": 0,
            }

        ctx_str = ""
        if context:
            ctx_items = [f"{k}: {v}" for k, v in list(context.items())[:5]]
            ctx_str = "\nContext:\n" + "\n".join(ctx_items)

        system = (
            "You are a capable AI assistant. Complete the given task thoroughly "
            "and return a useful, actionable result."
        )
        user = f"Task: {task}{ctx_str}"

        try:
            response = await ai.complete(
                system=system,
                user=user,
                max_tokens=800,
                agent_name="cognitive_agent_fallback",
            )
            if response and response.success and response.content:
                return {
                    "task": task,
                    "result": response.content.strip(),
                    "confidence": 0.7,
                    "reasoning_steps": ["Direct AI call (no LangGraph)"],
                    "plan": ["Execute task directly"],
                    "status": "done",
                    "iterations": 1,
                }
        except Exception as exc:
            logger.error("[CognitiveAgent %s] fallback AI call failed: %s", self.agent_id, exc)

        return {
            "task": task,
            "result": "",
            "confidence": 0.0,
            "reasoning_steps": ["Fallback AI call failed"],
            "plan": [],
            "status": "failed",
            "iterations": 0,
        }


# ── singleton factory ─────────────────────────────────────────────────────────


def get_cognitive_agent(agent_id: str = "", max_iterations: int = 3) -> CognitiveAgent:
    """
    Return the module-level CognitiveAgent singleton.

    The first call creates the instance; subsequent calls return the same object.
    Pass agent_id / max_iterations only on first call — they are ignored
    if the singleton already exists.
    """
    global _cognitive_agent
    if _cognitive_agent is None:
        _cognitive_agent = CognitiveAgent(agent_id=agent_id, max_iterations=max_iterations)
    return _cognitive_agent
