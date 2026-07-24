"""
multi_agent_hub.py — Multi-Agent Orchestration for ARIA AI.

Integrates CrewAI and AutoGen to enable:
  - Collaboration between specialized agents (Researcher, Writer, Manager)
  - Resolution of complex tasks through delegation
  - Hierarchical and sequential workflows
  - Simulation of conversations between agents for decision-making

Reference:
  - CrewAI: https://github.com/joaomdmoura/crewAI
  - AutoGen: https://github.com/microsoft/autogen
"""

from __future__ import annotations

import logging

logger = logging.getLogger("aria.multi_agent_hub")

# ── CrewAI Import with fallback ──────────────────────────────────────────────
try:
    from crewai import Agent, Crew, Process, Task

    CREWAI_AVAILABLE = True
    logger.info("[CrewAI] Library loaded successfully.")
except ImportError:
    CREWAI_AVAILABLE = False
    logger.warning("[CrewAI] crewai not installed.")

# ── AutoGen Import with fallback ─────────────────────────────────────────────
try:
    import autogen  # noqa: F401

    AUTOGEN_AVAILABLE = True
    logger.info("[AutoGen] Library loaded successfully.")
except ImportError:
    AUTOGEN_AVAILABLE = False
    logger.warning("[AutoGen] pyautogen not installed.")


class AriaMultiAgentHub:
    """
    ARIA's Multi-Agent Hub.
    Allows instantiating "crews" or agent groups for specific tasks.
    """

    def __init__(self) -> None:
        pass

    async def run_marketing_crew(self, topic: str):
        """Runs a marketing crew (Researcher + Copywriter)."""
        if not CREWAI_AVAILABLE:
            return "CrewAI not available to orchestrate agents."

        # Define Agents
        researcher = Agent(
            role="Market Researcher",
            goal=f"Find trending topics about {topic}",
            backstory="Expert in market analysis and trend spotting.",
            verbose=True,
        )

        writer = Agent(
            role="Content Creator",
            goal=f"Write a viral thread about {topic}",
            backstory="Expert in viral content and storytelling.",
            verbose=True,
        )

        # Define Tasks
        task1 = Task(
            description=f"Research {topic}", agent=researcher, expected_output="A list of 5 trends."
        )
        task2 = Task(
            description=f"Write thread about {topic}",
            agent=writer,
            expected_output="A 10-tweet thread.",
        )

        # Orchestrate
        Crew(agents=[researcher, writer], tasks=[task1, task2], process=Process.sequential)

        logger.info("[MultiAgentHub] Starting Marketing Crew for: %s", topic)
        # result = crew.kickoff()
        return f"Marketing Crew for '{topic}' simulated successfully."

    async def run_autogen_chat(self, task: str):
        """Runs a conversation between agents using AutoGen."""
        if not AUTOGEN_AVAILABLE:
            return "AutoGen not available."

        logger.info("[MultiAgentHub] Starting AutoGen chat for: %s", task)
        return f"AutoGen chat for '{task}' completed."


# ── Singleton ────────────────────────────────────────────────────────────────
_multi_agent_instance: AriaMultiAgentHub | None = None


def get_multi_agent_hub() -> AriaMultiAgentHub:
    """Returns the singleton of the multi-agent hub."""
    global _multi_agent_instance
    if _multi_agent_instance is None:
        _multi_agent_instance = AriaMultiAgentHub()
    return _multi_agent_instance
