"""
crew_engine.py — Multi-agent collaboration (CrewAI style) for ARIA AI.

Orchestrates teams of specialized agents that collaborate sequentially.
Each team member receives the accumulated work of the previous ones as context.

Predefined crews:
  - research_crew:  Researcher → Analyst → Writer
  - content_crew:   Researcher → SEO Strategist → Editor
  - dev_crew:       Product Manager → Developer → QA
  - sales_crew:     Market Analyst → Sales Strategist → Copywriter
  - launch_crew:    Strategist → Marketing Director → Financial Analyst
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("aria.crew")


@dataclass
class CrewMember:
    role: str
    goal: str
    agent_type: str  # Maps to BusinessHub: research|content|marketing|sales|developer|finance|ceo
    output: str | None = None


@dataclass
class CrewRun:
    id: str
    crew_name: str
    mission: str
    members: list[CrewMember]
    final_output: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    success: bool = False
    error: str | None = None

    def summary(self) -> dict:
        return {
            "id": self.id,
            "crew": self.crew_name,
            "mission": self.mission[:120],
            "success": self.success,
            "members": [{"role": m.role, "done": bool(m.output)} for m in self.members],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


CREW_TEMPLATES: dict[str, list[dict]] = {
    "research_crew": [
        {
            "role": "Senior Researcher",
            "goal": "Thoroughly research the topic: data, trends, key sources, relevant statistics, and current context.",
            "agent_type": "research",
        },
        {
            "role": "Strategic Analyst",
            "goal": "Analyze the researcher's findings. Identify patterns, opportunities, risks, and actionable conclusions.",
            "agent_type": "ceo",
        },
        {
            "role": "Executive Writer",
            "goal": "Transform the analysis into a clear, structured, ready-to-use final report. Executive summary + key points + next steps.",
            "agent_type": "content",
        },
    ],
    "content_crew": [
        {
            "role": "Content Researcher",
            "goal": "Research the topic, find unique angles, supporting data, and real examples to enrich the content.",
            "agent_type": "research",
        },
        {
            "role": "SEO Strategist",
            "goal": "Define structure, primary keywords, marketing angle, and optimal format for maximum visibility.",
            "agent_type": "marketing",
        },
        {
            "role": "Writer and Editor",
            "goal": "Create the polished final content: winning introduction, structured body, CTA, and optimized for publishing.",
            "agent_type": "content",
        },
    ],
    "dev_crew": [
        {
            "role": "Product Manager",
            "goal": "Define detailed technical requirements, use cases, system architecture, and success criteria.",
            "agent_type": "ceo",
        },
        {
            "role": "Senior Developer",
            "goal": "Implement the complete technical solution based on the PM's requirements. Functional, documented code.",
            "agent_type": "developer",
        },
        {
            "role": "QA Engineer",
            "goal": "Review the code, identify bugs and edge cases, suggest improvements, and create documentation for the solution.",
            "agent_type": "research",
        },
    ],
    "sales_crew": [
        {
            "role": "Market Analyst",
            "goal": "Research the target market, customer segments, competitors, pricing, and penetration opportunities.",
            "agent_type": "research",
        },
        {
            "role": "Sales Strategist",
            "goal": "Design a complete sales strategy: value proposition, objections, pipeline, and conversion process.",
            "agent_type": "sales",
        },
        {
            "role": "Conversion Copywriter",
            "goal": "Create the sales copy: emails, sales page, scripts, and high-conversion marketing materials.",
            "agent_type": "marketing",
        },
    ],
    "launch_crew": [
        {
            "role": "Product Strategist",
            "goal": "Define positioning, unique value proposition, go-to-market strategy, and key launch messages.",
            "agent_type": "ceo",
        },
        {
            "role": "Marketing Director",
            "goal": "Create the complete launch campaign: social media, email marketing, content calendar, and PR.",
            "agent_type": "marketing",
        },
        {
            "role": "Financial Analyst",
            "goal": "Project success metrics, pricing model, acquisition costs, break-even, and revenue projections.",
            "agent_type": "finance",
        },
    ],
    "venture_crew": [
        {
            "role": "Business Analyst",
            "goal": "Validate the business model, analyze viability, TAM, competition, and barriers to entry.",
            "agent_type": "research",
        },
        {
            "role": "Financial Strategist",
            "goal": "Project financials: runway, pricing, unit economics, valuation, and growth scenarios.",
            "agent_type": "finance",
        },
        {
            "role": "Pitch Specialist",
            "goal": "Create the complete pitch deck and materials for investors. Compelling story with solid data.",
            "agent_type": "content",
        },
    ],
}


class CrewEngine:
    """
    Orchestrates teams of specialized agents in sequential pipelines.
    Each agent's output enriches the next one's context.
    """

    def __init__(self) -> None:
        self._runs: dict[str, CrewRun] = {}

    async def run(
        self,
        mission: str,
        crew_name: str = "research_crew",
        context: str = "",
        on_progress: Callable | None = None,
    ) -> CrewRun:
        """
        Runs a predefined crew sequentially.
        on_progress(step_num, total, member_role) → called after each step.
        """
        template = CREW_TEMPLATES.get(crew_name, CREW_TEMPLATES["research_crew"])
        members = [CrewMember(**m) for m in template]
        run = CrewRun(
            id=str(uuid.uuid4())[:8], crew_name=crew_name, mission=mission, members=members
        )
        self._runs[run.id] = run

        accumulated = context
        all_outputs: list[str] = []
        any_success = False
        last_error: str | None = None

        from apps.core.agents.business_hub import BusinessHub

        hub = BusinessHub()

        for i, member in enumerate(members):
            if on_progress:
                with contextlib.suppress(Exception):
                    await on_progress(i + 1, len(members), member.role)

            agent_prompt = (
                f"TEAM MISSION: {mission}\n\n"
                f"YOUR ROLE: {member.role}\n"
                f"YOUR GOAL: {member.goal}\n"
            )
            if accumulated:
                agent_prompt += f"\nTEAM'S PREVIOUS WORK:\n{accumulated[:3500]}"

            try:
                result = await hub.dispatch(member.agent_type, agent_prompt, {})
                if not result.get("success", True):
                    member.output = f"[Error: {result.get('error', 'agent failed')}]"
                    last_error = result.get("error") or "agent failed"
                    logger.warning(
                        "[Crew:%s] member '%s' failed: %s", run.id, member.role, last_error
                    )
                else:
                    output = (
                        result.get("output")
                        or result.get("result")
                        or result.get("plan")
                        or str(result)
                    )
                    member.output = str(output)[:3000]
                    any_success = True
            except Exception as exc:
                member.output = f"[Error: {exc}]"
                last_error = str(exc)
                logger.warning("[Crew:%s] member '%s' failed: %s", run.id, member.role, exc)

            all_outputs.append(f"### {member.role}\n{member.output}")
            accumulated = "\n\n".join(all_outputs)

        run.final_output = await self._synthesize(mission, members)
        run.completed_at = datetime.now(UTC).isoformat()
        run.success = any_success
        run.error = None if any_success else (last_error or "all team members failed")
        return run

    async def run_custom(
        self,
        mission: str,
        roles: list[str],
        context: str = "",
    ) -> CrewRun:
        """
        Creates and runs a custom crew from a free-text list of roles.
        Automatically maps each role to the most suitable business agent.
        """
        # NOTE: keyword list intentionally mixes English and Spanish terms —
        # it matches free-text role names a caller may supply in either
        # language, so do not translate the keyword values themselves.
        role_to_agent = [
            (["invest", "research", "analiz"], "research"),
            (["market", "seo", "social", "campañ"], "marketing"),
            (["venta", "sales", "negoci"], "sales"),
            (["develop", "código", "program", "tech"], "developer"),
            (["content", "redact", "escrib", "copy"], "content"),
            (["finanz", "cfo", "contab", "presupuest"], "finance"),
            (["ceo", "director", "estrateg", "product"], "ceo"),
        ]

        def map_role(role: str) -> str:
            r = role.lower()
            for keywords, agent in role_to_agent:
                if any(k in r for k in keywords):
                    return agent
            return "ceo"

        members = [
            CrewMember(
                role=r, goal=f"Execute your part of the mission as {r}", agent_type=map_role(r)
            )
            for r in roles[:5]
        ]
        run = CrewRun(
            id=str(uuid.uuid4())[:8], crew_name="custom", mission=mission, members=members
        )
        self._runs[run.id] = run

        from apps.core.agents.business_hub import BusinessHub

        hub = BusinessHub()
        accumulated = context
        all_outputs: list[str] = []
        any_success = False
        last_error: str | None = None

        for member in members:
            prompt = f"Mission: {mission}\nRole: {member.role}\n" + (
                f"\nPrevious context:\n{accumulated[:2500]}" if accumulated else ""
            )
            try:
                result = await hub.dispatch(member.agent_type, prompt, {})
                if not result.get("success", True):
                    member.output = f"[Error: {result.get('error', 'agent failed')}]"
                    last_error = result.get("error") or "agent failed"
                else:
                    member.output = str(result.get("output") or result)[:2500]
                    any_success = True
            except Exception as exc:
                member.output = f"[Error: {exc}]"
                last_error = str(exc)
            all_outputs.append(f"### {member.role}\n{member.output}")
            accumulated = "\n\n".join(all_outputs)

        run.final_output = await self._synthesize(mission, members)
        run.completed_at = datetime.now(UTC).isoformat()
        run.success = any_success
        run.error = None if any_success else (last_error or "all team members failed")
        return run

    def list_crews(self) -> list[str]:
        return list(CREW_TEMPLATES.keys())

    def list_runs(self, limit: int = 10) -> list[dict]:
        return [
            r.summary()
            for r in sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)[:limit]
        ]

    # ── PRIVATE ───────────────────────────────────────────────────────────────

    async def _synthesize(self, mission: str, members: list[CrewMember]) -> str:
        from apps.core.tools.ai_client import AIModel, get_ai_client

        client = get_ai_client()
        contributions = "\n\n".join(f"**{m.role}:**\n{m.output or 'N/A'}" for m in members)
        resp = await client.complete(
            model=AIModel.STRATEGY,
            system=(
                "You are the team's executive director. Synthesize the work into a final, "
                "cohesive, non-redundant, professional, ready-to-use output."
            ),
            user=(
                f"Mission: {mission}\n\n"
                f"Team contributions:\n{contributions[:5000]}\n\n"
                "Final synthesized output:"
            ),
            max_tokens=2500,
        )
        if not resp.success:
            return "\n\n".join(f"**{m.role}:**\n{m.output or 'N/A'}" for m in members)
        return resp.content


_engine: CrewEngine | None = None


def get_crew_engine() -> CrewEngine:
    global _engine
    if _engine is None:
        _engine = CrewEngine()
    return _engine
