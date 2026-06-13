"""Async stage-based cognitive pipeline with resumable execution."""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class StageResult:
    stage_name: str
    status: StageStatus
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "stage_name": self.stage_name,
            "status": self.status.value,
            "output": self.output if isinstance(self.output, (str, int, float, bool, dict, list, type(None))) else str(self.output),
            "error": self.error,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class PipelineRun:
    id: str
    input_text: str
    context: dict[str, Any]
    stage_results: list[StageResult] = field(default_factory=list)
    status: PipelineStatus = PipelineStatus.CREATED
    final_output: Any = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None
    total_duration_ms: float = 0.0

    @property
    def resume_from_stage(self) -> int:
        """Index of the first non-completed stage."""
        for i, r in enumerate(self.stage_results):
            if r.status not in (StageStatus.DONE, StageStatus.SKIPPED):
                return i
        return len(self.stage_results)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "input_text": self.input_text,
            "status": self.status.value,
            "final_output": self.final_output,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "total_duration_ms": self.total_duration_ms,
            "stages": [r.to_dict() for r in self.stage_results],
        }


# Stage function signature: async (run: PipelineRun, stage_input: Any) -> Any
StageFn = Callable[["PipelineRun", Any], Any]


@dataclass
class PipelineStage:
    name: str
    fn: StageFn
    timeout_seconds: float = 30.0
    skip_on_error: bool = False


class CognitivePipeline:
    """
    Five-stage async pipeline: Intent → Context → Reason → Plan → Execute.
    Each stage receives the output of the previous stage as its input.
    The pipeline is resumable from any completed stage checkpoint.
    """

    def __init__(self) -> None:
        self._stages: list[PipelineStage] = []
        self._runs: dict[str, PipelineRun] = {}

    def add_stage(
        self,
        name: str,
        fn: StageFn,
        timeout_seconds: float = 30.0,
        skip_on_error: bool = False,
    ) -> "CognitivePipeline":
        self._stages.append(PipelineStage(name=name, fn=fn, timeout_seconds=timeout_seconds, skip_on_error=skip_on_error))
        return self

    async def run(
        self,
        input_text: str,
        context: Optional[dict] = None,
        run_id: Optional[str] = None,
    ) -> PipelineRun:
        run = PipelineRun(
            id=run_id or f"pipe_{uuid.uuid4().hex[:12]}",
            input_text=input_text,
            context=context or {},
            stage_results=[StageResult(s.name, StageStatus.PENDING) for s in self._stages],
        )
        self._runs[run.id] = run
        return await self._execute(run, start_idx=0)

    async def resume(self, run_id: str) -> Optional[PipelineRun]:
        run = self._runs.get(run_id)
        if run is None:
            return None
        start_idx = run.resume_from_stage
        return await self._execute(run, start_idx=start_idx)

    async def _execute(self, run: PipelineRun, start_idx: int) -> PipelineRun:
        run.status = PipelineStatus.RUNNING
        wall_start = time.monotonic()

        stage_input: Any = run.input_text
        # Carry forward output from already-completed stages
        for i in range(start_idx):
            prev = run.stage_results[i]
            if prev.status == StageStatus.DONE and prev.output is not None:
                stage_input = prev.output

        try:
            for i in range(start_idx, len(self._stages)):
                stage = self._stages[i]
                result = run.stage_results[i]
                result.status = StageStatus.RUNNING
                result.started_at = datetime.now(timezone.utc).isoformat()
                t0 = time.monotonic()

                try:
                    output = await asyncio.wait_for(
                        stage.fn(run, stage_input),
                        timeout=stage.timeout_seconds,
                    )
                    result.output = output
                    result.status = StageStatus.DONE
                    stage_input = output
                except asyncio.TimeoutError:
                    result.error = f"Stage '{stage.name}' timed out after {stage.timeout_seconds}s"
                    if stage.skip_on_error:
                        result.status = StageStatus.SKIPPED
                    else:
                        result.status = StageStatus.FAILED
                        run.status = PipelineStatus.FAILED
                        run.error = result.error
                        break
                except Exception as exc:
                    result.error = str(exc)
                    if stage.skip_on_error:
                        result.status = StageStatus.SKIPPED
                    else:
                        result.status = StageStatus.FAILED
                        run.status = PipelineStatus.FAILED
                        run.error = result.error
                        break
                finally:
                    result.duration_ms = (time.monotonic() - t0) * 1000
                    result.finished_at = datetime.now(timezone.utc).isoformat()
            else:
                # All stages completed
                run.status = PipelineStatus.DONE
                run.final_output = stage_input
        finally:
            run.total_duration_ms = (time.monotonic() - wall_start) * 1000
            run.finished_at = datetime.now(timezone.utc).isoformat()

        return run

    def get_run(self, run_id: str) -> Optional[PipelineRun]:
        return self._runs.get(run_id)

    def recent_runs(self, n: int = 10) -> list[PipelineRun]:
        runs = list(self._runs.values())
        return sorted(runs, key=lambda r: r.created_at, reverse=True)[:n]


def build_aria_pipeline(ai_client: Any = None) -> CognitivePipeline:
    """
    Constructs the canonical 5-stage ARIA cognitive pipeline.
    Each stage is independently replaceable; ai_client may be None (stages degrade gracefully).
    """
    pipe = CognitivePipeline()

    async def intent_stage(run: PipelineRun, text: Any) -> dict:
        """Classify intent and extract entities from raw input."""
        stripped = str(text).strip()
        intent = "general"
        if any(k in stripped.lower() for k in ["/plan", "planear", "create a plan"]):
            intent = "planning"
        elif any(k in stripped.lower() for k in ["/think", "reason", "analyze"]):
            intent = "reasoning"
        elif any(k in stripped.lower() for k in ["income", "revenue", "money", "earn"]):
            intent = "income"
        elif any(k in stripped.lower() for k in ["report", "status", "how"]):
            intent = "status"
        return {"text": stripped, "intent": intent, "entities": []}

    async def context_stage(run: PipelineRun, intent_data: Any) -> dict:
        """Retrieve relevant memory context for the request."""
        result = dict(intent_data) if isinstance(intent_data, dict) else {"text": str(intent_data), "intent": "general"}
        try:
            from apps.core.memory.orchestrator import get_memory_orchestrator
            ctx = await get_memory_orchestrator().retrieve(result.get("text", ""), top_k=5)
            result["memory_context"] = {
                "fact_count": len(ctx.facts),
                "procedure_count": len(ctx.procedures),
                "event_count": len(ctx.recent_events),
                "top_items": [i.__dict__ for i in ctx.ranked_items[:3]] if ctx.ranked_items else [],
            }
        except Exception:
            result["memory_context"] = {}
        return result

    async def reason_stage(run: PipelineRun, ctx_data: Any) -> dict:
        """Apply reasoning engine to produce a conclusion."""
        result = dict(ctx_data) if isinstance(ctx_data, dict) else {"text": str(ctx_data)}
        if ai_client is not None:
            try:
                from apps.core.cognition.reasoning_engine import get_reasoning_engine
                engine = get_reasoning_engine(ai_client)
                question = result.get("text", "")
                reasoning = await engine.reason(question, context=result.get("memory_context", {}), max_steps=3)
                result["reasoning"] = {
                    "conclusion": reasoning.conclusion,
                    "confidence": reasoning.confidence,
                    "action": reasoning.action_recommendation,
                    "is_high_confidence": reasoning.is_high_confidence,
                }
            except Exception as exc:
                result["reasoning"] = {"conclusion": "", "confidence": 0.0, "error": str(exc)}
        else:
            result["reasoning"] = {"conclusion": "Reasoning unavailable (no AI client)", "confidence": 0.0}
        return result

    async def plan_stage(run: PipelineRun, reason_data: Any) -> dict:
        """Convert reasoning output into an executable plan if needed."""
        result = dict(reason_data) if isinstance(reason_data, dict) else {"text": str(reason_data)}
        intent = result.get("intent", "general")
        if intent == "planning" and ai_client is not None:
            try:
                from apps.core.cognition.planner import get_planner
                planner = get_planner()
                plan = await planner.create_plan(
                    goal=result.get("text", ""),
                    context=result.get("memory_context", {}),
                    ai_client=ai_client,
                )
                result["plan"] = plan.to_dict() if plan else None
            except Exception as exc:
                result["plan"] = {"error": str(exc)}
        else:
            result["plan"] = None
        return result

    async def execute_stage(run: PipelineRun, plan_data: Any) -> str:
        """Synthesize final output from all prior stages."""
        if not isinstance(plan_data, dict):
            return str(plan_data)

        reasoning = plan_data.get("reasoning", {})
        plan = plan_data.get("plan")
        intent = plan_data.get("intent", "general")

        if plan and not plan.get("error"):
            task_count = len(plan.get("tasks", []))
            return f"[{intent.upper()}] Plan created with {task_count} tasks. {reasoning.get('conclusion', '')}"
        elif reasoning.get("conclusion"):
            conf = reasoning.get("confidence", 0)
            return f"[{intent.upper()}] {reasoning['conclusion']} (confidence: {conf:.0%})"
        else:
            return f"[{intent.upper()}] Processed: {plan_data.get('text', '')[:200]}"

    pipe.add_stage("intent", intent_stage, timeout_seconds=5.0, skip_on_error=True)
    pipe.add_stage("context", context_stage, timeout_seconds=10.0, skip_on_error=True)
    pipe.add_stage("reason", reason_stage, timeout_seconds=25.0, skip_on_error=True)
    pipe.add_stage("plan", plan_stage, timeout_seconds=30.0, skip_on_error=True)
    pipe.add_stage("execute", execute_stage, timeout_seconds=10.0, skip_on_error=False)

    return pipe


_pipeline: Optional[CognitivePipeline] = None


def get_cognitive_pipeline(ai_client: Any = None) -> CognitivePipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = build_aria_pipeline(ai_client)
    return _pipeline
