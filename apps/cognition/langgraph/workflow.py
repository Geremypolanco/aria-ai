"""
ARIA LangGraph — StateGraph workflow builder.

Constructs the cognitive workflow DAG:
  analyze → plan → execute → reflect
                               ↓
                   [done → END | thinking → analyze | failed → failure → END]

If langgraph is not installed, build_cognitive_workflow() returns None and the
CognitiveAgent falls back to a direct AI call.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("aria.cognition.workflow")

try:
    from langgraph.graph import END, StateGraph
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False
    StateGraph = None  # type: ignore[assignment,misc]
    END = None  # type: ignore[assignment]

from apps.cognition.langgraph.agent_state import AgentState
from apps.cognition.langgraph.nodes import (
    analyze_task,
    create_plan,
    execute_step,
    handle_failure,
    reflect,
)


def _route_after_reflect(state: AgentState) -> str:
    """
    Conditional edge function called after the reflect node.

    Possible returns (must match keys in add_conditional_edges map):
      "thinking"  → loop back to analyze
      "executing" → continue to execute (more plan steps remain)
      "done"      → END
      "failed"    → failure node
    """
    status = state.get("status", "done")
    if status in ("thinking", "executing", "planning"):
        return "thinking"
    if status == "failed":
        return "failed"
    return "done"


def build_cognitive_workflow():
    """
    Build and compile the LangGraph StateGraph.

    Returns a compiled runnable graph or None if LangGraph is unavailable.
    """
    if not _LANGGRAPH_AVAILABLE:
        logger.warning("[workflow] langgraph not installed — workflow unavailable")
        return None

    try:
        workflow = StateGraph(AgentState)

        # Register nodes
        workflow.add_node("analyze", analyze_task)
        workflow.add_node("plan", create_plan)
        workflow.add_node("execute", execute_step)
        workflow.add_node("reflect", reflect)
        workflow.add_node("failure", handle_failure)

        # Entry point
        workflow.set_entry_point("analyze")

        # Fixed edges
        workflow.add_edge("analyze", "plan")
        workflow.add_edge("plan", "execute")
        workflow.add_edge("execute", "reflect")

        # Conditional: reflect decides whether to loop, finish, or fail
        workflow.add_conditional_edges(
            "reflect",
            _route_after_reflect,
            {
                "thinking": "analyze",   # low confidence → retry
                "done": END,
                "failed": "failure",
            },
        )
        workflow.add_edge("failure", END)

        compiled = workflow.compile()
        logger.info("[workflow] Cognitive workflow compiled successfully")
        return compiled

    except Exception as exc:
        logger.error("[workflow] Failed to compile workflow: %s", exc)
        return None
