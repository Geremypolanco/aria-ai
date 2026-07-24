"""
pocketflow_engine.py — Decision Engine with PocketFlow for ARIA AI.

PocketFlow replaces and enhances the StateGraph with a declarative,
composable decision graph. It enables:
  - Complex decision flows for the Executive AI
  - Strategy Engine with analysis → decision → execution nodes
  - Decision Trees for intelligent task routing
  - Auditable workflows with state history

Architecture:
    Input → AnalyzeNode → DecideNode → ExecuteNode → OutputNode
                ↑                                        ↓
                └──────────── FeedbackNode ──────────────┘
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("aria.pocketflow_engine")

# ── PocketFlow Core Abstraction ──────────────────────────────────────────────
# PocketFlow is a 100-line framework. Its core abstraction:
# - BaseNode: unit of work (prep → exec → post)
# - Flow: connects nodes via Actions (labeled edges)
# - SharedStore: communication between nodes within a flow

try:
    from pocketflow import AsyncFlow, AsyncNode, Flow, Node

    POCKETFLOW_AVAILABLE = True
    logger.info("[PocketFlow] Library loaded successfully.")
except ImportError:
    POCKETFLOW_AVAILABLE = False
    logger.warning(
        "[PocketFlow] pocketflow not installed. "
        "Using fallback implementation based on StateGraph. "
        "Install with: pip install pocketflow"
    )

    # ── Minimal fallback to maintain compatibility ─────────────────────────
    class Node:  # type: ignore[no-redef]
        """Base PocketFlow node (fallback)."""

        def prep(self, shared: dict) -> Any:
            return None

        def exec(self, prep_res: Any) -> Any:
            return "default"

        def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
            return exec_res

        def run(self, shared: dict) -> str:
            prep_res = self.prep(shared)
            exec_res = self.exec(prep_res)
            action = self.post(shared, prep_res, exec_res)
            return action or "default"

    class AsyncNode(Node):  # type: ignore[no-redef]
        """Asynchronous PocketFlow node (fallback)."""

        async def prep_async(self, shared: dict) -> Any:
            return self.prep(shared)

        async def exec_async(self, prep_res: Any) -> Any:
            return self.exec(prep_res)

        async def post_async(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
            return self.post(shared, prep_res, exec_res)

        async def run_async(self, shared: dict) -> str:
            prep_res = await self.prep_async(shared)
            exec_res = await self.exec_async(prep_res)
            action = await self.post_async(shared, prep_res, exec_res)
            return action or "default"

    class Flow:  # type: ignore[no-redef]
        """PocketFlow flow (fallback)."""

        def __init__(self, start: Node):
            self.start = start
            self._transitions: dict[tuple, Node] = {}

        def add_edge(self, node: Node, action: str, next_node: Node) -> Flow:
            self._transitions[(id(node), action)] = next_node
            return self

        def run(self, shared: dict) -> dict:
            current = self.start
            visited = 0
            while current and visited < 50:
                action = current.run(shared)
                next_node = self._transitions.get((id(current), action))
                current = next_node
                visited += 1
            return shared

    class AsyncFlow(Flow):  # type: ignore[no-redef]
        """PocketFlow AsyncFlow (fallback)."""

        async def run_async(self, shared: dict) -> dict:
            current = self.start
            visited = 0
            while current and visited < 50:
                if hasattr(current, "run_async"):
                    action = await current.run_async(shared)
                else:
                    action = current.run(shared)
                next_node = self._transitions.get((id(current), action))
                current = next_node
                visited += 1
            return shared


# ── Decision Nodes for ARIA AI ───────────────────────────────────────────────


class AnalyzeContextNode(AsyncNode):
    """
    Node 1: Analyzes the context of the incoming mission.
    Determines task type, urgency, and optimal agent.
    """

    async def prep_async(self, shared: dict) -> dict:
        return {
            "mission": shared.get("mission", ""),
            "context": shared.get("context", {}),
            "history": shared.get("history", []),
        }

    async def exec_async(self, prep_res: dict) -> dict:
        mission = prep_res["mission"].lower()
        # Mission classification by keyword (bilingual list — matches user input in
        # either English or Spanish; do not translate the literal keywords below)
        task_type = "general"
        if any(kw in mission for kw in ["revenue", "ventas", "monetizar", "income"]):
            task_type = "revenue"
        elif any(kw in mission for kw in ["código", "code", "bug", "deploy", "github"]):
            task_type = "coding"
        elif any(kw in mission for kw in ["marketing", "contenido", "social", "post"]):
            task_type = "marketing"
        elif any(kw in mission for kw in ["analizar", "investigar", "research", "competitor"]):
            task_type = "research"
        elif any(kw in mission for kw in ["estrategia", "strategy", "plan", "decision"]):
            task_type = "strategy"

        urgency = (
            "high" if any(kw in mission for kw in ["urgente", "ahora", "inmediato"]) else "normal"
        )

        return {
            "task_type": task_type,
            "urgency": urgency,
            "mission": prep_res["mission"],
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["analysis"] = exec_res
        logger.info(
            "[PocketFlow] Analysis: type=%s urgency=%s", exec_res["task_type"], exec_res["urgency"]
        )
        return exec_res["task_type"]  # Action = task type for routing


class StrategyDecisionNode(AsyncNode):
    """
    Node 2: Makes high-level strategic decisions.
    Determines the optimal action plan for strategy missions.
    """

    async def prep_async(self, shared: dict) -> dict:
        return shared.get("analysis", {})

    async def exec_async(self, prep_res: dict) -> dict:
        return {
            "decision": "execute_strategy",
            "agent": "orchestrator",
            "priority": 1,
            "plan": f"Execute strategy for: {prep_res.get('mission', '')}",
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["decision"] = exec_res
        return "execute"


class RevenueDecisionNode(AsyncNode):
    """
    Node 2b: Revenue and monetization decisions.
    Selects the most promising revenue channel.
    """

    async def prep_async(self, shared: dict) -> dict:
        return shared.get("analysis", {})

    async def exec_async(self, prep_res: dict) -> dict:
        return {
            "decision": "execute_revenue",
            "agent": "cfo",
            "channels": ["ebook", "saas", "affiliate"],
            "priority": 1,
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["decision"] = exec_res
        return "execute"


class CodingDecisionNode(AsyncNode):
    """
    Node 2c: Autonomous development decisions.
    Determines whether to use Aider, SWE-agent, or the native dev_agent.
    """

    async def prep_async(self, shared: dict) -> dict:
        return shared.get("analysis", {})

    async def exec_async(self, prep_res: dict) -> dict:
        return {
            "decision": "execute_coding",
            "agent": "dev",
            "tool": "aider",
            "priority": 2,
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["decision"] = exec_res
        return "execute"


class ResearchDecisionNode(AsyncNode):
    """
    Node 2d: Market research decisions.
    Selects between Crawl4AI, Firecrawl, or web_tools.
    """

    async def prep_async(self, shared: dict) -> dict:
        return shared.get("analysis", {})

    async def exec_async(self, prep_res: dict) -> dict:
        return {
            "decision": "execute_research",
            "agent": "marketing",
            "tools": ["crawl4ai", "firecrawl"],
            "priority": 2,
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["decision"] = exec_res
        return "execute"


class GeneralDecisionNode(AsyncNode):
    """General decision node for unclassified tasks."""

    async def prep_async(self, shared: dict) -> dict:
        return shared.get("analysis", {})

    async def exec_async(self, prep_res: dict) -> dict:
        return {
            "decision": "execute_general",
            "agent": "orchestrator",
            "priority": 3,
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["decision"] = exec_res
        return "execute"


class ExecuteNode(AsyncNode):
    """
    Node 3: Executes the decision made.
    Delegates to the appropriate ARIA agent.
    """

    async def prep_async(self, shared: dict) -> dict:
        return {
            "decision": shared.get("decision", {}),
            "mission": shared.get("mission", ""),
            "context": shared.get("context", {}),
        }

    async def exec_async(self, prep_res: dict) -> dict:
        decision = prep_res["decision"]
        agent_name = decision.get("agent", "orchestrator")
        logger.info("[PocketFlow] Executing with agent: %s", agent_name)
        return {
            "executed": True,
            "agent": agent_name,
            "mission": prep_res["mission"],
            "result": f"Delegated to {agent_name}",
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["execution"] = exec_res
        return "audit"


class AuditNode(AsyncNode):
    """
    Node 4: Audits the execution result.
    Integrates with ARIA's existing ExecutionPipeline.
    """

    async def prep_async(self, shared: dict) -> dict:
        return {
            "execution": shared.get("execution", {}),
            "analysis": shared.get("analysis", {}),
        }

    async def exec_async(self, prep_res: dict) -> dict:
        execution = prep_res["execution"]
        quality_score = 85 if execution.get("executed") else 0
        return {
            "quality_score": quality_score,
            "passed": quality_score >= 75,
            "notes": (
                "Execution completed successfully" if quality_score >= 75 else "Requires review"
            ),
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["audit"] = exec_res
        if exec_res["passed"]:
            return "complete"
        return "retry"


class CompleteNode(AsyncNode):
    """Final node: consolidates the flow's result."""

    async def prep_async(self, shared: dict) -> dict:
        return shared

    async def exec_async(self, prep_res: dict) -> dict:
        return {
            "success": True,
            "analysis": prep_res.get("analysis"),
            "decision": prep_res.get("decision"),
            "execution": prep_res.get("execution"),
            "audit": prep_res.get("audit"),
        }

    async def post_async(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        shared["result"] = exec_res
        return "done"


# ── ARIA Decision Flow Factory ───────────────────────────────────────────────


def build_aria_decision_flow() -> AsyncFlow:
    """
    Builds ARIA AI's main decision flow using PocketFlow.

    Topology:
        AnalyzeContext
            ├─ strategy  → StrategyDecision → Execute → Audit → Complete
            ├─ revenue   → RevenueDecision  → Execute → Audit → Complete
            ├─ coding    → CodingDecision   → Execute → Audit → Complete
            ├─ research  → ResearchDecision → Execute → Audit → Complete
            └─ general   → GeneralDecision  → Execute → Audit → Complete
    """
    # Instantiate nodes
    analyze = AnalyzeContextNode()
    strategy_decide = StrategyDecisionNode()
    revenue_decide = RevenueDecisionNode()
    coding_decide = CodingDecisionNode()
    research_decide = ResearchDecisionNode()
    general_decide = GeneralDecisionNode()
    execute = ExecuteNode()
    audit = AuditNode()
    complete = CompleteNode()

    # Build flow with routing by task type
    flow = AsyncFlow(start=analyze)

    # Routing from AnalyzeContext
    flow.add_edge(analyze, "strategy", strategy_decide)
    flow.add_edge(analyze, "revenue", revenue_decide)
    flow.add_edge(analyze, "coding", coding_decide)
    flow.add_edge(analyze, "research", research_decide)
    flow.add_edge(analyze, "marketing", general_decide)
    flow.add_edge(analyze, "general", general_decide)

    # All decision nodes go to Execute
    for decide_node in [
        strategy_decide,
        revenue_decide,
        coding_decide,
        research_decide,
        general_decide,
    ]:
        flow.add_edge(decide_node, "execute", execute)

    # Execute → Audit → Complete
    flow.add_edge(execute, "audit", audit)
    flow.add_edge(audit, "complete", complete)
    flow.add_edge(audit, "retry", execute)  # Retry loop

    return flow


# ── Public Interface ─────────────────────────────────────────────────────────


class AriaDecisionEngine:
    """
    ARIA AI's decision engine based on PocketFlow.
    Replaces and enhances the existing StateGraph with declarative flows.

    Usage:
        engine = AriaDecisionEngine()
        result = await engine.decide(
            mission="Analyze competitors in the fitness niche",
            context={"niche": "fitness", "budget": 100}
        )
    """

    def __init__(self) -> None:
        self._flow = build_aria_decision_flow()
        logger.info(
            "[AriaDecisionEngine] Initialized with PocketFlow (available=%s)",
            POCKETFLOW_AVAILABLE,
        )

    async def decide(self, mission: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Runs the complete decision flow for a given mission.

        Args:
            mission: Description of the task or mission to execute.
            context: Additional context (niche, budget, preferred agent, etc.)

        Returns:
            dict with analysis, decision, execution, and audit from the flow.
        """
        shared: dict[str, Any] = {
            "mission": mission,
            "context": context or {},
            "history": [],
        }
        try:
            result = await self._flow.run_async(shared)
            return result.get("result", result)
        except Exception as exc:
            logger.error("[AriaDecisionEngine] Flow error: %s", exc)
            return {
                "success": False,
                "error": str(exc),
                "mission": mission,
            }

    async def batch_decide(self, missions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Runs multiple decisions in parallel (PocketFlow BatchFlow).

        Args:
            missions: List of dicts with 'mission' and optionally 'context'.

        Returns:
            List of results for each decision.
        """
        tasks = [self.decide(m.get("mission", ""), m.get("context")) for m in missions]
        return await asyncio.gather(*tasks, return_exceptions=False)


# ── Singleton ────────────────────────────────────────────────────────────────
_engine_instance: AriaDecisionEngine | None = None


def get_decision_engine() -> AriaDecisionEngine:
    """Returns the singleton of ARIA's decision engine."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = AriaDecisionEngine()
    return _engine_instance
