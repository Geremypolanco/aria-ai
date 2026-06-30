"""
Unified Framework Integration Hub for ARIA OS.

Integrates best-of-breed open-source frameworks:
- LangGraph: Stateful reasoning with graph-based workflows
- CrewAI: Multi-agent orchestration and collaboration
- DSPy: Prompt optimization and program synthesis
- Temporal: Durable workflow orchestration
- LangChain: Memory, tools, retrieval

All frameworks communicate via unified Event Bus and fallback gracefully.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("aria.integration")


# ── FRAMEWORK DETECTION ────────────────────────────────────────────────────


class FrameworkStatus(str, Enum):
    """Status of each integrated framework."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


@dataclass
class FrameworkInfo:
    """Framework capability info."""

    name: str
    status: FrameworkStatus
    version: str = "unknown"
    capabilities: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "version": self.version,
            "capabilities": self.capabilities,
            "error": self.error,
        }


class IntegrationHub:
    """
    Central hub for managing all framework integrations.

    Provides:
    - Unified interface to all frameworks
    - Fallback chains when a framework is unavailable
    - Health checking and monitoring
    - Auto-detection of installed packages
    """

    def __init__(self):
        self._frameworks: Dict[str, FrameworkInfo] = {}
        self._fallback_chains: Dict[str, List[str]] = {}
        self._initialized = False

    async def initialize(self) -> Dict[str, FrameworkInfo]:
        """
        Detect and initialize all available frameworks.

        Returns: {framework_name: FrameworkInfo}
        """
        logger.info("🔍 Scanning for integrated frameworks...")

        # Check each framework
        frameworks_to_check = [
            ("langgraph", self._check_langgraph),
            ("crewai", self._check_crewai),
            ("dspy", self._check_dspy),
            ("langchain", self._check_langchain),
            ("temporalio", self._check_temporal),
        ]

        for name, checker in frameworks_to_check:
            info = await checker()
            self._frameworks[name] = info
            logger.info(f"  {name}: {info.status.value}")

        # Set up fallback chains
        self._setup_fallback_chains()
        self._initialized = True

        logger.info("✅ Framework integration complete")
        return self._frameworks

    async def _check_langgraph(self) -> FrameworkInfo:
        """Check LangGraph availability."""
        try:
            import langgraph

            version = getattr(langgraph, "__version__", "unknown")
            return FrameworkInfo(
                name="LangGraph",
                status=FrameworkStatus.AVAILABLE,
                version=version,
                capabilities=[
                    "stateful_reasoning",
                    "graph_workflows",
                    "multi_agent_loops",
                    "persistence",
                ],
            )
        except ImportError as e:
            return FrameworkInfo(
                name="LangGraph",
                status=FrameworkStatus.UNAVAILABLE,
                error=str(e),
                capabilities=[],
            )

    async def _check_crewai(self) -> FrameworkInfo:
        """Check CrewAI availability."""
        try:
            import crewai

            version = getattr(crewai, "__version__", "unknown")
            return FrameworkInfo(
                name="CrewAI",
                status=FrameworkStatus.AVAILABLE,
                version=version,
                capabilities=[
                    "multi_agent_teams",
                    "role_based_agents",
                    "task_delegation",
                    "collaboration",
                ],
            )
        except ImportError as e:
            return FrameworkInfo(
                name="CrewAI",
                status=FrameworkStatus.UNAVAILABLE,
                error=str(e),
                capabilities=[],
            )

    async def _check_dspy(self) -> FrameworkInfo:
        """Check DSPy availability."""
        try:
            import dspy

            version = getattr(dspy, "__version__", "unknown")
            return FrameworkInfo(
                name="DSPy",
                status=FrameworkStatus.AVAILABLE,
                version=version,
                capabilities=[
                    "prompt_optimization",
                    "program_synthesis",
                    "module_abstraction",
                    "pipeline_optimization",
                ],
            )
        except ImportError as e:
            return FrameworkInfo(
                name="DSPy",
                status=FrameworkStatus.UNAVAILABLE,
                error=str(e),
                capabilities=[],
            )

    async def _check_langchain(self) -> FrameworkInfo:
        """Check LangChain availability."""
        try:
            import langchain

            version = langchain.__version__
            return FrameworkInfo(
                name="LangChain",
                status=FrameworkStatus.AVAILABLE,
                version=version,
                capabilities=[
                    "chains",
                    "memory",
                    "tools",
                    "retrieval",
                    "agents",
                ],
            )
        except ImportError as e:
            return FrameworkInfo(
                name="LangChain",
                status=FrameworkStatus.UNAVAILABLE,
                error=str(e),
                capabilities=[],
            )

    async def _check_temporal(self) -> FrameworkInfo:
        """Check Temporal SDK availability."""
        try:
            import temporalio

            version = temporalio.__version__
            return FrameworkInfo(
                name="Temporal",
                status=FrameworkStatus.AVAILABLE,
                version=version,
                capabilities=[
                    "durable_workflows",
                    "activity_execution",
                    "retry_logic",
                    "state_persistence",
                ],
            )
        except ImportError as e:
            return FrameworkInfo(
                name="Temporal",
                status=FrameworkStatus.UNAVAILABLE,
                error=str(e),
                capabilities=[],
            )

    def _setup_fallback_chains(self) -> None:
        """Define fallback chains for critical operations."""
        self._fallback_chains = {
            "reasoning": [
                "langgraph",  # Primary: stateful reasoning
                "crewai",  # Fallback: multi-agent
                "dspy",  # Fallback: prompt-based
            ],
            "task_execution": [
                "temporalio",  # Primary: durable workflows
                "crewai",  # Fallback: agent-based
            ],
            "prompt_optimization": [
                "dspy",  # Primary: optimization
                "langchain",  # Fallback: basic chains
            ],
            "multi_agent": [
                "crewai",  # Primary: team orchestration
                "langgraph",  # Fallback: graph-based
            ],
        }

    async def get_reasoning_engine(self) -> Optional[str]:
        """
        Get best available reasoning engine.

        Returns: framework name to use, or None
        """
        if not self._initialized:
            await self.initialize()

        for framework in self._fallback_chains.get("reasoning", []):
            if framework in self._frameworks:
                info = self._frameworks[framework]
                if info.status == FrameworkStatus.AVAILABLE:
                    return framework
        return None

    async def get_task_executor(self) -> Optional[str]:
        """Get best available task executor."""
        if not self._initialized:
            await self.initialize()

        for framework in self._fallback_chains.get("task_execution", []):
            if framework in self._frameworks:
                info = self._frameworks[framework]
                if info.status == FrameworkStatus.AVAILABLE:
                    return framework
        return None

    async def get_multi_agent_framework(self) -> Optional[str]:
        """Get best available multi-agent framework."""
        if not self._initialized:
            await self.initialize()

        for framework in self._fallback_chains.get("multi_agent", []):
            if framework in self._frameworks:
                info = self._frameworks[framework]
                if info.status == FrameworkStatus.AVAILABLE:
                    return framework
        return None

    async def get_prompt_optimizer(self) -> Optional[str]:
        """Get best available prompt optimizer."""
        if not self._initialized:
            await self.initialize()

        for framework in self._fallback_chains.get("prompt_optimization", []):
            if framework in self._frameworks:
                info = self._frameworks[framework]
                if info.status == FrameworkStatus.AVAILABLE:
                    return framework
        return None

    def status(self) -> Dict[str, FrameworkInfo]:
        """Get status of all frameworks."""
        return {name: info for name, info in self._frameworks.items()}

    def available_frameworks(self) -> List[str]:
        """List all available frameworks."""
        return [
            name
            for name, info in self._frameworks.items()
            if info.status == FrameworkStatus.AVAILABLE
        ]


# ── LANGGRAPH INTEGRATION ──────────────────────────────────────────────────


class LangGraphIntegration:
    """Wrapper for LangGraph stateful reasoning."""

    @staticmethod
    async def create_workflow(nodes: Dict[str, Callable], edges: List[tuple]) -> Optional[Any]:
        """
        Create a LangGraph workflow.

        Args:
            nodes: {node_name: callable}
            edges: [(from_node, to_node), ...]

        Returns: Compiled graph or None if LangGraph unavailable
        """
        try:
            from langgraph.graph import StateGraph, END

            graph = StateGraph(dict)

            for name, func in nodes.items():
                graph.add_node(name, func)

            for from_node, to_node in edges:
                if to_node == "END":
                    graph.add_edge(from_node, END)
                else:
                    graph.add_edge(from_node, to_node)

            return graph.compile()
        except ImportError:
            logger.warning("LangGraph not available, skipping workflow creation")
            return None

    @staticmethod
    async def invoke(graph: Any, input_data: dict) -> Optional[dict]:
        """Invoke a LangGraph workflow."""
        try:
            if graph is None:
                return None
            return await graph.ainvoke(input_data)
        except Exception as e:
            logger.error(f"LangGraph invocation failed: {e}")
            return None


# ── CREWAI INTEGRATION ─────────────────────────────────────────────────────


class CrewAIIntegration:
    """Wrapper for CrewAI multi-agent orchestration."""

    @staticmethod
    async def create_crew(
        agents_config: List[Dict[str, Any]], tasks_config: List[Dict[str, Any]]
    ) -> Optional[Any]:
        """
        Create a CrewAI crew.

        Args:
            agents_config: List of agent configs with role, goal, tools
            tasks_config: List of task configs

        Returns: Crew instance or None
        """
        try:
            from crewai import Agent, Task, Crew

            agents = []
            for cfg in agents_config:
                agent = Agent(
                    role=cfg.get("role", "Agent"),
                    goal=cfg.get("goal", "Complete tasks"),
                    tools=cfg.get("tools", []),
                )
                agents.append(agent)

            tasks = []
            for i, cfg in enumerate(tasks_config):
                task = Task(
                    description=cfg.get("description", ""),
                    agent=agents[min(i, len(agents) - 1)],
                )
                tasks.append(task)

            crew = Crew(agents=agents, tasks=tasks)
            return crew
        except ImportError:
            logger.warning("CrewAI not available, skipping crew creation")
            return None

    @staticmethod
    async def execute_crew(crew: Any) -> Optional[dict]:
        """Execute a CrewAI crew."""
        try:
            if crew is None:
                return None
            result = crew.kickoff()
            return {"output": result}
        except Exception as e:
            logger.error(f"CrewAI execution failed: {e}")
            return None


# ── DSPY INTEGRATION ───────────────────────────────────────────────────────


class DSPyIntegration:
    """Wrapper for DSPy prompt optimization."""

    @staticmethod
    async def optimize_module(
        module_class: type, train_examples: List[dict], metric_fn: Callable
    ) -> Optional[Any]:
        """
        Optimize a DSPy module.

        Args:
            module_class: DSPy module class
            train_examples: Training examples
            metric_fn: Function to evaluate quality

        Returns: Optimized module or None
        """
        try:
            import dspy
            from dspy.teleprompt import BootstrapFewShot

            teleprompter = BootstrapFewShot(metric=metric_fn)
            optimized = teleprompter.compile(module_class(), train_set=train_examples)
            return optimized
        except ImportError:
            logger.warning("DSPy not available, skipping optimization")
            return None

    @staticmethod
    async def predict(module: Any, **kwargs) -> Optional[str]:
        """Use DSPy module for prediction."""
        try:
            if module is None:
                return None
            return module(**kwargs)
        except Exception as e:
            logger.error(f"DSPy prediction failed: {e}")
            return None


# ── TEMPORAL INTEGRATION ───────────────────────────────────────────────────


class TemporalIntegration:
    """Wrapper for Temporal durable workflows."""

    @staticmethod
    async def register_workflow(workflow_class: type, task_queue: str) -> Optional[Any]:
        """Register a workflow with Temporal."""
        try:
            from temporalio import worker

            return worker.Worker(
                "localhost:7233",
                task_queue=task_queue,
                workflows=[workflow_class],
            )
        except ImportError:
            logger.warning("Temporal SDK not available, skipping workflow registration")
            return None

    @staticmethod
    async def execute_workflow(
        workflow_class: type, workflow_id: str, input_data: Any
    ) -> Optional[Any]:
        """Execute a Temporal workflow."""
        try:
            from temporalio.client import Client

            client = await Client.connect("localhost:7233")
            result = await client.execute_workflow(
                workflow_class.run,
                input_data,
                id=workflow_id,
                task_queue="default",
            )
            return result
        except Exception as e:
            logger.error(f"Temporal execution failed: {e}")
            return None


# ── SINGLETON ──────────────────────────────────────────────────────────────

_integration_hub: Optional[IntegrationHub] = None


async def get_integration_hub() -> IntegrationHub:
    """Get or create the global integration hub."""
    global _integration_hub
    if _integration_hub is None:
        _integration_hub = IntegrationHub()
        await _integration_hub.initialize()
    return _integration_hub
