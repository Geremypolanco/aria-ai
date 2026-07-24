"""
ExecutionPipeline — Execution pipeline with built-in auditing for ARIA AI.

Plan → Audit → Execute → Audit → (Iterate | Complete) architecture.
Guarantees minimum quality before delivering results to production.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from apps.core.agents.auditor_agent import AuditorAgent
from apps.core.agents.business_hub import BusinessHub
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.execution_pipeline")


class PipelineStage(StrEnum):
    PLAN = "plan"
    AUDIT_PLAN = "audit_plan"
    EXECUTE = "execute"
    AUDIT_OUTPUT = "audit_output"
    ITERATE = "iterate"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class PipelineRun:
    id: str
    mission: str
    agent_name: str
    stage: PipelineStage
    plan: str | None = None
    output: dict | None = None
    audit_results: list = field(default_factory=list)
    iterations: int = 0
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    success: bool = False
    error: str | None = None

    def summary(self) -> dict:
        """Returns a fully serializable dict of all fields."""
        return {
            "id": self.id,
            "mission": self.mission,
            "agent_name": self.agent_name,
            "stage": self.stage.value,
            "plan": self.plan,
            "output": self.output,
            "audit_results": self.audit_results,
            "iterations": self.iterations,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "success": self.success,
            "error": self.error,
        }


class ExecutionPipeline:
    """
    Execution pipeline with built-in auditing.

    Flow:
        PLAN → AUDIT_PLAN → EXECUTE → AUDIT_OUTPUT → COMPLETE
                                            ↕ (retry up to MAX_ITERATIONS)
                                         ITERATE

    Guarantees the output has quality >= MIN_QUALITY_SCORE before completing.
    """

    MAX_ITERATIONS: int = 3
    MIN_QUALITY_SCORE: int = 75

    def __init__(self) -> None:
        self._auditor = AuditorAgent()
        self._hub = BusinessHub()
        self._runs: dict[str, PipelineRun] = {}

    # ── MAIN PIPELINE ──────────────────────────────────────

    async def run(
        self,
        mission: str,
        agent_name: str = "auto",
        context: dict[str, Any] | None = None,
    ) -> PipelineRun:
        """
        Runs the full pipeline with Plan → Execute → Audit → (Iterate | Complete) auditing.

        Args:
            mission:    The mission to execute.
            agent_name: Name of the agent to use, or "auto" for auto-routing.
            context:    Additional context (parameters, input data, etc.).

        Returns:
            PipelineRun with the final state and all results.
        """
        run = PipelineRun(
            id=str(uuid.uuid4()),
            mission=mission,
            agent_name=agent_name,
            stage=PipelineStage.PLAN,
        )
        self._runs[run.id] = run
        ctx = dict(context or {})

        try:
            # ── STAGE 1: PLAN ──────────────────────────────
            self._transition(run, PipelineStage.PLAN)
            plan = await self._generate_plan(mission)
            run.plan = plan

            # ── STAGE 2: AUDIT PLAN ────────────────────────
            self._transition(run, PipelineStage.AUDIT_PLAN)
            plan_audit = await self._auditor.audit_plan(plan, mission)
            run.audit_results.append({"stage": "plan", "audit": plan_audit.to_dict()})

            if plan_audit.score < 50:
                logger.warning(
                    "[Pipeline %s] Plan audit FAIL (score=%d) — attempting to improve the plan",
                    run.id,
                    plan_audit.score,
                )
                plan = await self._improve_plan(plan, mission, plan_audit.reasoning)
                run.plan = plan

                # Re-audit the improved plan
                plan_audit2 = await self._auditor.audit_plan(plan, mission)
                run.audit_results.append({"stage": "plan_retry", "audit": plan_audit2.to_dict()})

                if plan_audit2.score < 50:
                    run.stage = PipelineStage.FAILED
                    run.error = (
                        f"Plan audit failed after improvement (score={plan_audit2.score}). "
                        f"Reason: {plan_audit2.reasoning}"
                    )
                    run.completed_at = datetime.utcnow()
                    logger.error("[Pipeline %s] FAILED in audit_plan", run.id)
                    return run

            # ── STAGE 3: EXECUTE ───────────────────────────
            self._transition(run, PipelineStage.EXECUTE)
            ctx["approved_plan"] = run.plan
            output = await self._hub.dispatch(agent_name, mission, dict(ctx))
            run.output = output

            # ── STAGE 4: AUDIT OUTPUT + ITERATE LOOP ───────
            self._transition(run, PipelineStage.AUDIT_OUTPUT)

            while True:
                output_audit = await self._auditor.audit_output(
                    output=run.output,
                    mission=mission,
                    original_plan=run.plan or "",
                )
                run.audit_results.append(
                    {"stage": f"output_iter_{run.iterations}", "audit": output_audit.to_dict()}
                )

                if output_audit.score >= self.MIN_QUALITY_SCORE:
                    # Quality threshold met → COMPLETE
                    break

                if run.iterations >= self.MAX_ITERATIONS:
                    # Max retries exhausted → complete with current result + audit note
                    logger.warning(
                        "[Pipeline %s] MAX_ITERATIONS (%d) reached. Completing with current result.",
                        run.id,
                        self.MAX_ITERATIONS,
                    )
                    if isinstance(run.output, dict):
                        run.output["_audit_verdict"] = output_audit.verdict
                        run.output["_audit_score"] = output_audit.score
                    break

                # Iterate: retry execute with feedback in context
                run.iterations += 1
                self._transition(run, PipelineStage.ITERATE)
                logger.info(
                    "[Pipeline %s] Iteration %d — score=%d < %d, retrying with feedback",
                    run.id,
                    run.iterations,
                    output_audit.score,
                    self.MIN_QUALITY_SCORE,
                )
                ctx["audit_feedback"] = output_audit.reasoning
                ctx["audit_issues"] = [
                    {"severity": i.severity, "description": i.description, "fix": i.fix}
                    for i in output_audit.issues
                ]
                ctx["approved_plan"] = run.plan
                self._transition(run, PipelineStage.AUDIT_OUTPUT)
                output = await self._hub.dispatch(agent_name, mission, dict(ctx))
                run.output = output

            # ── COMPLETE ────────────────────────────────────
            run.stage = PipelineStage.COMPLETE
            run.success = True
            logger.info("[Pipeline %s] COMPLETE — iterations=%d", run.id, run.iterations)

        except Exception as exc:
            run.stage = PipelineStage.FAILED
            run.error = str(exc)
            logger.error("[Pipeline %s] Unexpected exception: %s", run.id, exc, exc_info=True)

        finally:
            run.completed_at = datetime.utcnow()

        return run

    async def run_quick(
        self,
        mission: str,
        agent_name: str = "auto",
    ) -> dict[str, Any]:
        """
        Quick execution with no auditing — for simple tasks.
        Does not create a PipelineRun, does not audit, just dispatches directly.

        Returns:
            The agent's dispatch result.
        """
        logger.info("[Pipeline] run_quick: agent=%s mission=%s", agent_name, mission[:80])
        return await self._hub.dispatch(agent_name, mission, {"mission": mission})

    # ── RUN CACHE ──────────────────────────────────────────

    def get_run(self, run_id: str) -> PipelineRun | None:
        """Returns a cached PipelineRun by ID, or None if not found."""
        return self._runs.get(run_id)

    def list_runs(self, limit: int = 20) -> list[dict]:
        """Returns the last N runs as serializable summary dicts."""
        all_runs = list(self._runs.values())
        recent = all_runs[-limit:] if len(all_runs) > limit else all_runs
        return [r.summary() for r in reversed(recent)]

    # ── INTERNAL HELPERS ───────────────────────────────────

    def _transition(self, run: PipelineRun, stage: PipelineStage) -> None:
        """Logs and applies a stage transition."""
        run.stage = stage
        logger.info("[Pipeline %s] → Stage: %s", run.id, stage.value)

    async def _generate_plan(self, mission: str) -> str:
        """
        Generates a numbered plan for the mission using the auditor's AI.
        Produces clear, actionable, ordered steps.
        """
        system = (
            "You are an expert strategic planner. "
            "You break down complex missions into clear, ordered, executable steps. "
            "Each step must be concrete, verifiable, and assignable to a specialist agent."
        )
        user = (
            f"Break down this mission into a numbered execution plan:\n\nMISSION: {mission}\n\n"
            "Generate between 3 and 8 numbered steps. Each step must:\n"
            "- Be a concrete action (verb + object)\n"
            "- State the expected result\n"
            "- Be independently executable\n\n"
            "Format: 1. [Step]\n2. [Step]\n..."
        )
        response = await self._auditor.think(
            system=system,
            user=user,
            model=AIModel.STRATEGY,
        )
        if not response:
            # Minimal fallback plan
            return f"1. Analyze the mission: {mission}\n2. Execute the main task\n3. Verify results"
        return response.strip()

    async def _improve_plan(
        self,
        original_plan: str,
        mission: str,
        audit_feedback: str,
    ) -> str:
        """
        Improves a rejected plan using the audit feedback.
        """
        system = (
            "You are an expert strategic planner who improves plans based on critical feedback. "
            "You are direct and don't repeat the same mistakes."
        )
        user = (
            f"MISSION: {mission}\n\n"
            f"ORIGINAL PLAN (REJECTED):\n{original_plan}\n\n"
            f"AUDITOR FEEDBACK:\n{audit_feedback}\n\n"
            "Generate an improved plan that fixes all identified problems. "
            "Be specific and direct. Format: 1. [Step]\n2. [Step]\n..."
        )
        response = await self._auditor.think(
            system=system,
            user=user,
            model=AIModel.STRATEGY,
        )
        if not response:
            return original_plan  # Return original if AI unavailable
        return response.strip()


# ── SINGLETON ──────────────────────────────────────────────────────────────────

_pipeline: ExecutionPipeline | None = None


def get_pipeline() -> ExecutionPipeline:
    """Return the shared ExecutionPipeline singleton (preserves run history)."""
    global _pipeline
    if _pipeline is None:
        _pipeline = ExecutionPipeline()
    return _pipeline
