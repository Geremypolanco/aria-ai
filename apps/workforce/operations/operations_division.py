"""
ARIA AI — Operations Division
Handles project planning, research, support, scheduling, CRM, and automation specs.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.workforce.operations")

_CACHE_KEY = "workforce:operations:v1"
_CACHE_TTL = 86400 * 90  # 90 days

_PRIORITY_WEIGHTS = {"low": 1, "medium": 2, "high": 3, "urgent": 4}


# ── Domain object ──────────────────────────────────────────────────────────────


@dataclass
class OperationsTask:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task_type: str = ""  # "project_plan", "research", "support_response", "schedule", "crm_update"
    agent_type: str = (
        ""  # "project_manager", "virtual_assistant", "customer_support", "operations_specialist"
    )
    title: str = ""
    output: str = ""
    priority: str = "medium"  # "low"|"medium"|"high"|"urgent"
    estimated_minutes: int = 0
    status: str = "done"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "agent_type": self.agent_type,
            "title": self.title,
            "output": self.output,
            "priority": self.priority,
            "estimated_minutes": self.estimated_minutes,
            "status": self.status,
            "created_at": self.created_at,
        }


# ── Operations Division ────────────────────────────────────────────────────────


class OperationsDivision:
    """AI-powered operations workforce division."""

    def __init__(self):
        self._cache = get_cache()
        self._ai = get_ai_client()
        self._tasks: list[dict] = []

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _load_tasks(self) -> None:
        data = await self._cache.get(_CACHE_KEY)
        if data and isinstance(data, list):
            self._tasks = data

    async def _save_tasks(self) -> None:
        await self._cache.set(_CACHE_KEY, self._tasks, ttl_seconds=_CACHE_TTL)

    async def _run_ai(
        self, system: str, user: str, model: AIModel = AIModel.STRATEGY, max_tokens: int = 800
    ) -> str:
        resp = await self._ai.complete(system=system, user=user, model=model, max_tokens=max_tokens)
        if resp.success:
            return resp.content.strip()
        return "Operations task completed. Review output and proceed accordingly."

    def _store_task(self, task: OperationsTask) -> OperationsTask:
        self._tasks.append(task.to_dict())
        return task

    # ── Core Operations Methods ──────────────────────────────────────────────

    async def create_project_plan(
        self,
        project_name: str,
        objectives: list,
        deadline_days: int,
        team_size: int = 1,
    ) -> OperationsTask:
        """AI produces project plan with milestones, tasks, and risks."""
        await self._load_tasks()

        objectives_text = "\n".join(f"  - {obj}" for obj in objectives)
        output = await self._run_ai(
            system=(
                "You are an expert project manager. Create a comprehensive project plan with: "
                "1) Project overview and scope, 2) Key milestones with dates, "
                "3) Task breakdown (grouped by phase), 4) Resource allocation, "
                "5) Risk assessment with mitigation strategies, 6) Success criteria. "
                "Be specific with timelines relative to the deadline."
            ),
            user=(
                f"Project: {project_name}\nObjectives:\n{objectives_text}\n"
                f"Deadline: {deadline_days} days\nTeam Size: {team_size} people"
            ),
            model=AIModel.STRATEGY,
        )

        task = OperationsTask(
            task_type="project_plan",
            agent_type="project_manager",
            title=f"Project Plan: {project_name[:60]}",
            output=output,
            priority="high",
            estimated_minutes=deadline_days * 60 // max(team_size, 1),
            status="done",
        )
        self._store_task(task)
        await self._save_tasks()
        return task

    async def research_topic(
        self,
        topic: str,
        depth: str = "medium",
        output_format: str = "summary",
    ) -> OperationsTask:
        """AI researches and summarizes a topic."""
        await self._load_tasks()

        depth_instructions = {
            "light": "Provide a quick 3-5 bullet point overview with key facts.",
            "medium": "Provide a structured summary with key points, context, and implications.",
            "deep": "Provide a comprehensive analysis with background, current state, trends, opportunities, and strategic recommendations.",
        }
        depth_instruction = depth_instructions.get(depth, depth_instructions["medium"])

        format_instruction = (
            "Format as a structured executive summary with headers."
            if output_format == "summary"
            else "Format as a detailed report with sections and sub-sections."
        )

        output = await self._run_ai(
            system=(
                f"You are an expert research analyst. {depth_instruction} {format_instruction} "
                f"Include: key facts, relevant statistics, trends, and actionable insights."
            ),
            user=f"Research Topic: {topic}",
            model=AIModel.STRATEGY,
            max_tokens=1000,
        )

        priority_map = {"light": "low", "medium": "medium", "deep": "high"}
        time_map = {"light": 30, "medium": 90, "deep": 240}

        task = OperationsTask(
            task_type="research",
            agent_type="virtual_assistant",
            title=f"Research: {topic[:60]}",
            output=output,
            priority=priority_map.get(depth, "medium"),
            estimated_minutes=time_map.get(depth, 90),
            status="done",
        )
        self._store_task(task)
        await self._save_tasks()
        return task

    async def draft_support_response(
        self,
        customer_issue: str,
        context: dict = None,
    ) -> OperationsTask:
        """AI drafts professional customer support response."""
        if context is None:
            context = {}
        await self._load_tasks()

        context_text = ""
        if context:
            context_text = "\nContext:\n" + "\n".join(f"  {k}: {v}" for k, v in context.items())

        output = await self._run_ai(
            system=(
                "You are an expert customer support specialist. Draft a professional, empathetic response that: "
                "1) Acknowledges the customer's issue with empathy, 2) Provides a clear solution or next steps, "
                "3) Sets realistic expectations, 4) Ends with a positive closing. "
                "Be warm, professional, and solution-focused. Keep it concise."
            ),
            user=f"Customer Issue: {customer_issue}{context_text}",
            model=AIModel.FAST,
            max_tokens=400,
        )

        task = OperationsTask(
            task_type="support_response",
            agent_type="customer_support",
            title=f"Support Response: {customer_issue[:50]}",
            output=output,
            priority="high",
            estimated_minutes=15,
            status="done",
        )
        self._store_task(task)
        await self._save_tasks()
        return task

    async def schedule_week(
        self,
        priorities: list,
        hours_available: float = 40.0,
    ) -> OperationsTask:
        """AI produces weekly schedule with time blocks."""
        await self._load_tasks()

        priorities_text = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(priorities))
        output = await self._run_ai(
            system=(
                "You are an expert productivity and scheduling specialist. Create an optimized weekly schedule with: "
                "1) Daily time blocks (morning/afternoon/evening), 2) Priority tasks allocated to peak energy times, "
                "3) Buffer time for unexpected work, 4) Deep work vs shallow work blocks, "
                "5) Specific time allocations for each priority. Use a clear, scannable format."
            ),
            user=(
                f"Weekly Priorities:\n{priorities_text}\n"
                f"Hours Available: {hours_available} hours"
            ),
            model=AIModel.STRATEGY,
        )

        task = OperationsTask(
            task_type="schedule",
            agent_type="virtual_assistant",
            title=f"Weekly Schedule ({len(priorities)} priorities)",
            output=output,
            priority="medium",
            estimated_minutes=int(hours_available * 60),
            status="done",
        )
        self._store_task(task)
        await self._save_tasks()
        return task

    async def update_crm_notes(
        self,
        customer_name: str,
        interaction_summary: str,
        next_steps: list,
    ) -> OperationsTask:
        """AI structures CRM notes for the customer interaction."""
        await self._load_tasks()

        next_steps_text = "\n".join(f"  - {step}" for step in next_steps)
        output = await self._run_ai(
            system=(
                "You are a CRM specialist. Structure customer interaction notes for a CRM system with: "
                "1) Interaction summary (professional, concise), 2) Customer sentiment assessment, "
                "3) Key discussion points, 4) Action items with owners, "
                "5) Follow-up date recommendation, 6) Deal stage assessment. "
                "Format clearly for CRM entry."
            ),
            user=(
                f"Customer: {customer_name}\nInteraction Summary: {interaction_summary}\n"
                f"Next Steps:\n{next_steps_text}"
            ),
            model=AIModel.FAST,
            max_tokens=400,
        )

        task = OperationsTask(
            task_type="crm_update",
            agent_type="operations_specialist",
            title=f"CRM Notes: {customer_name}",
            output=output,
            priority="medium",
            estimated_minutes=10,
            status="done",
        )
        self._store_task(task)
        await self._save_tasks()
        return task

    async def process_automation_spec(
        self,
        workflow_description: str,
    ) -> OperationsTask:
        """AI produces automation spec with trigger, steps, and tools."""
        await self._load_tasks()

        output = await self._run_ai(
            system=(
                "You are a process automation expert. Create a detailed automation specification with: "
                "1) Trigger conditions (what starts the workflow), 2) Step-by-step process flow, "
                "3) Tool/platform recommendations for each step, 4) Error handling and fallbacks, "
                "5) Testing checklist, 6) Expected time savings per week. "
                "Be specific about the tools (Zapier, Make.com, n8n, APIs, etc.)."
            ),
            user=f"Workflow to Automate: {workflow_description}",
            model=AIModel.STRATEGY,
        )

        task = OperationsTask(
            task_type="project_plan",
            agent_type="operations_specialist",
            title=f"Automation Spec: {workflow_description[:50]}",
            output=output,
            priority="high",
            estimated_minutes=120,
            status="done",
        )
        self._store_task(task)
        await self._save_tasks()
        return task

    # ── Division-level methods ───────────────────────────────────────────────

    def operations_stats(self) -> dict:
        """Return aggregate stats across all operations tasks."""
        if not self._tasks:
            return {
                "total_tasks": 0,
                "by_agent_type": {},
                "avg_priority_distribution": {},
            }

        by_agent: dict[str, int] = {}
        priority_dist: dict[str, int] = {}
        for t in self._tasks:
            agent = t.get("agent_type", "unknown")
            by_agent[agent] = by_agent.get(agent, 0) + 1
            priority = t.get("priority", "medium")
            priority_dist[priority] = priority_dist.get(priority, 0) + 1

        return {
            "total_tasks": len(self._tasks),
            "by_agent_type": by_agent,
            "avg_priority_distribution": priority_dist,
        }

    def recent_tasks(self, limit: int = 10) -> list[dict]:
        """Return most recent operations tasks."""
        sorted_tasks = sorted(self._tasks, key=lambda t: t.get("created_at", 0), reverse=True)
        return sorted_tasks[:limit]

    def pending_tasks(self) -> list[dict]:
        """Return tasks with status not 'done'."""
        return [t for t in self._tasks if t.get("status") != "done"]


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: OperationsDivision | None = None


def get_operations_division() -> OperationsDivision:
    global _instance
    if _instance is None:
        _instance = OperationsDivision()
    return _instance
