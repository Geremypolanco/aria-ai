"""
ARIA AI — Engineering Division
Phase 10: Professional engineering capability system.

Six engineering agents:
  - frontend_engineer: React/HTML component code
  - backend_engineer: Python/FastAPI endpoint code
  - mlops_engineer: ML pipeline/deployment config
  - api_integration_engineer: API integration code
  - qa_engineer: Test suites
  - automation_engineer: Automation scripts
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

# ── Redis configuration ────────────────────────────────────────────────────────
_REDIS_KEY = "workforce:engineering:v1"
_TTL_90D = 60 * 60 * 24 * 90

# ── Cost estimates per task type ───────────────────────────────────────────────
_TASK_COSTS: dict[str, float] = {
    "frontend_engineer": 0.02,
    "backend_engineer": 0.03,
    "mlops_engineer": 0.05,
    "api_integration_engineer": 0.03,
    "qa_engineer": 0.02,
    "automation_engineer": 0.04,
}


# ══════════════════════════════════════════════════════════════════════════════
# Domain object
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class WorkTask:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task_type: str = ""
    agent_type: str = ""
    title: str = ""
    inputs: dict = field(default_factory=dict)
    output: str = ""
    quality_score: float = 0.0
    estimated_cost_usd: float = 0.0
    duration_ms: float = 0.0
    status: str = "pending"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "agent_type": self.agent_type,
            "title": self.title,
            "inputs": self.inputs,
            "output": self.output,
            "quality_score": self.quality_score,
            "estimated_cost_usd": self.estimated_cost_usd,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "created_at": self.created_at,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Engineering Division
# ══════════════════════════════════════════════════════════════════════════════

class EngineeringDivision:
    """
    Manages a fleet of AI-powered engineering agents.
    State is persisted in Redis (key: workforce:engineering:v1, TTL 90d).
    """

    def __init__(self):
        self._tasks: list[dict] = []

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _quality_score(self, content: str) -> float:
        """Score based on word count — richer output → higher quality."""
        words = len(content.split())
        score = 0.5 + (words / 2000)
        return min(score, 0.95)

    async def _load(self) -> None:
        cache = get_cache()
        data = await cache.get(_REDIS_KEY)
        if isinstance(data, dict):
            self._tasks = data.get("tasks", [])
        elif isinstance(data, list):
            self._tasks = data

    async def _save(self) -> None:
        cache = get_cache()
        await cache.set(_REDIS_KEY, {"tasks": self._tasks}, ttl_seconds=_TTL_90D)

    async def _run_task(
        self,
        task_type: str,
        agent_type: str,
        title: str,
        inputs: dict,
        system_prompt: str,
        user_prompt: str,
        model: AIModel = AIModel.FAST,
    ) -> WorkTask:
        task = WorkTask(
            task_type=task_type,
            agent_type=agent_type,
            title=title,
            inputs=inputs,
            estimated_cost_usd=_TASK_COSTS.get(agent_type, 0.03),
            status="running",
        )
        t0 = time.time()
        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=system_prompt,
                user=user_prompt,
                model=model,
                max_tokens=1500,
            )
            task.duration_ms = (time.time() - t0) * 1000
            if resp.success:
                task.output = resp.content
                task.quality_score = self._quality_score(resp.content)
                task.status = "done"
            else:
                task.output = "# Task failed — AI returned no content"
                task.quality_score = 0.0
                task.status = "failed"
        except Exception as exc:
            task.duration_ms = (time.time() - t0) * 1000
            task.output = f"# Error: {exc}"
            task.quality_score = 0.0
            task.status = "failed"

        await self._load()
        self._tasks.append(task.to_dict())
        await self._save()
        return task

    # ── Engineering agents ─────────────────────────────────────────────────────

    async def frontend_task(self, title: str, spec: dict) -> WorkTask:
        """Generate React/HTML component code from a spec."""
        system = (
            "You are a senior frontend engineer. Generate production-quality React "
            "component code with TypeScript, proper props interface, styled-components "
            "or Tailwind CSS, accessibility attributes, and JSDoc comments. "
            "Output only the code file, no explanations."
        )
        user = (
            f"Task: {title}\n\n"
            f"Component spec:\n{spec}\n\n"
            "Generate the complete React component implementation."
        )
        return await self._run_task(
            task_type="build_component",
            agent_type="frontend_engineer",
            title=title,
            inputs={"spec": spec},
            system_prompt=system,
            user_prompt=user,
            model=AIModel.FAST,
        )

    async def backend_task(self, title: str, spec: dict) -> WorkTask:
        """Generate Python/FastAPI endpoint code from a spec."""
        system = (
            "You are a senior backend engineer. Generate production-quality Python "
            "FastAPI endpoint code with Pydantic models, dependency injection, error "
            "handling, and docstrings. Follow REST best practices. "
            "Output only the code file."
        )
        user = (
            f"Task: {title}\n\n"
            f"Endpoint spec:\n{spec}\n\n"
            "Generate the complete FastAPI router implementation."
        )
        return await self._run_task(
            task_type="build_endpoint",
            agent_type="backend_engineer",
            title=title,
            inputs={"spec": spec},
            system_prompt=system,
            user_prompt=user,
            model=AIModel.FAST,
        )

    async def mlops_task(self, title: str, spec: dict) -> WorkTask:
        """Generate ML pipeline/deployment configuration."""
        system = (
            "You are a senior MLOps engineer. Generate production-quality ML pipeline "
            "configuration including data preprocessing, model training, evaluation, "
            "and deployment scripts. Use best practices for reproducibility and monitoring. "
            "Output YAML configs and Python scripts as needed."
        )
        user = (
            f"Task: {title}\n\n"
            f"Pipeline spec:\n{spec}\n\n"
            "Generate the complete ML pipeline implementation."
        )
        return await self._run_task(
            task_type="build_ml_pipeline",
            agent_type="mlops_engineer",
            title=title,
            inputs={"spec": spec},
            system_prompt=system,
            user_prompt=user,
            model=AIModel.STRATEGY,
        )

    async def api_integration_task(
        self, title: str, api_name: str, endpoints: list
    ) -> WorkTask:
        """Generate API integration code for a third-party service."""
        system = (
            "You are a senior integration engineer. Generate production-quality Python "
            "API client code with async support, retry logic, rate limiting, error "
            "handling, and type hints. Include a usage example. "
            "Output only the code file."
        )
        user = (
            f"Task: {title}\n\n"
            f"API: {api_name}\n"
            f"Endpoints to integrate:\n{endpoints}\n\n"
            "Generate the complete API integration client."
        )
        return await self._run_task(
            task_type="api_integration",
            agent_type="api_integration_engineer",
            title=title,
            inputs={"api_name": api_name, "endpoints": endpoints},
            system_prompt=system,
            user_prompt=user,
            model=AIModel.FAST,
        )

    async def qa_task(self, title: str, code_to_test: str) -> WorkTask:
        """Generate a comprehensive test suite for the given code."""
        system = (
            "You are a senior QA engineer. Generate a comprehensive pytest test suite "
            "covering unit tests, edge cases, error conditions, and integration tests. "
            "Use fixtures, parametrize, and mocks appropriately. "
            "Output only the test file."
        )
        user = (
            f"Task: {title}\n\n"
            f"Code to test:\n```python\n{code_to_test}\n```\n\n"
            "Generate the complete pytest test suite."
        )
        return await self._run_task(
            task_type="write_test",
            agent_type="qa_engineer",
            title=title,
            inputs={"code_snippet": code_to_test[:500]},
            system_prompt=system,
            user_prompt=user,
            model=AIModel.FAST,
        )

    async def automation_task(self, title: str, workflow: dict) -> WorkTask:
        """Generate an automation script for a given workflow."""
        system = (
            "You are a senior automation engineer. Generate production-quality Python "
            "automation scripts with error handling, logging, retry logic, and CLI "
            "argument parsing. Use async where appropriate. "
            "Output only the script file."
        )
        user = (
            f"Task: {title}\n\n"
            f"Workflow definition:\n{workflow}\n\n"
            "Generate the complete automation script."
        )
        return await self._run_task(
            task_type="build_automation",
            agent_type="automation_engineer",
            title=title,
            inputs={"workflow": workflow},
            system_prompt=system,
            user_prompt=user,
            model=AIModel.FAST,
        )

    # ── Division-level methods ─────────────────────────────────────────────────

    async def execute_sprint(self, tasks: list[dict]) -> list[WorkTask]:
        """
        Run multiple tasks sequentially.

        Each item in `tasks` must have:
          - "type": one of "frontend", "backend", "mlops", "api", "qa", "automation"
          - "title": task title
          - Additional keys depending on type (see individual methods)
        """
        results: list[WorkTask] = []
        for task_def in tasks:
            task_type = task_def.get("type", "")
            title = task_def.get("title", "Untitled")
            try:
                if task_type == "frontend":
                    wt = await self.frontend_task(title, task_def.get("spec", {}))
                elif task_type == "backend":
                    wt = await self.backend_task(title, task_def.get("spec", {}))
                elif task_type == "mlops":
                    wt = await self.mlops_task(title, task_def.get("spec", {}))
                elif task_type == "api":
                    wt = await self.api_integration_task(
                        title,
                        task_def.get("api_name", ""),
                        task_def.get("endpoints", []),
                    )
                elif task_type == "qa":
                    wt = await self.qa_task(title, task_def.get("code_to_test", ""))
                elif task_type == "automation":
                    wt = await self.automation_task(title, task_def.get("workflow", {}))
                else:
                    wt = WorkTask(
                        title=title,
                        task_type=task_type,
                        status="failed",
                        output=f"Unknown task type: {task_type}",
                    )
                results.append(wt)
            except Exception as exc:
                results.append(
                    WorkTask(title=title, status="failed", output=str(exc))
                )
        return results

    def engineering_stats(self) -> dict:
        """Return aggregate statistics for all engineering tasks."""
        total = len(self._tasks)
        by_agent: dict[str, int] = {}
        total_quality = 0.0
        total_cost = 0.0
        for t in self._tasks:
            agent = t.get("agent_type", "unknown")
            by_agent[agent] = by_agent.get(agent, 0) + 1
            total_quality += t.get("quality_score", 0.0)
            total_cost += t.get("estimated_cost_usd", 0.0)
        return {
            "total_tasks": total,
            "by_agent_type": by_agent,
            "avg_quality_score": round(total_quality / total, 3) if total else 0.0,
            "total_cost_usd": round(total_cost, 4),
        }

    def recent_tasks(self, limit: int = 10) -> list[dict]:
        """Return the most recent tasks, newest first."""
        return list(reversed(self._tasks))[:limit]

    def task_by_id(self, task_id: str) -> Optional[dict]:
        """Look up a task by its ID."""
        for t in self._tasks:
            if t.get("task_id") == task_id:
                return t
        return None


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: Optional[EngineeringDivision] = None


def get_engineering_division() -> EngineeringDivision:
    global _instance
    if _instance is None:
        _instance = EngineeringDivision()
    return _instance
