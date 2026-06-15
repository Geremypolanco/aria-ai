"""WorkflowMemory — Stores successful and failed workflow patterns for self-improvement."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_KEY = "memory:workflow:v1"
_TTL = 86400 * 180


@dataclass
class WorkflowRecord:
    record_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    workflow_name: str = ""
    workflow_type: str = ""
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    success: bool = True
    success_score: float = 0.0
    duration_seconds: float = 0.0
    error: str = ""
    lessons: list = field(default_factory=list)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class WorkflowMemory:
    def __init__(self) -> None:
        self._records: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, list):
                    self._records = data
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, self._records[-500:], ttl_seconds=_TTL)
        except Exception:
            pass

    async def record(self, workflow_name: str, workflow_type: str, inputs: dict, outputs: dict,
                     success: bool = True, success_score: float = 0.8,
                     duration_seconds: float = 0.0, error: str = "") -> WorkflowRecord:
        await self._load()
        lessons = []
        try:
            ai = get_ai_client()
            status = "succeeded" if success else f"failed: {error}"
            resp = await ai.complete(
                system="Workflow analyst. Extract 2 concise lessons.",
                user=f"Workflow '{workflow_name}' ({workflow_type}) {status}. Score: {success_score}. Extract key lessons.",
                model=AIModel.FAST, max_tokens=150,
            )
            if resp.success and resp.content:
                lessons = [l.strip() for l in resp.content.strip().split("\n") if l.strip()][:3]
        except Exception:
            pass
        if not lessons:
            lessons = ["Track input quality for better outputs"] if success else [f"Fix error: {error[:100]}"]

        rec = WorkflowRecord(workflow_name=workflow_name, workflow_type=workflow_type,
                             inputs=inputs, outputs=outputs, success=success,
                             success_score=success_score, duration_seconds=duration_seconds,
                             error=error, lessons=lessons)
        self._records.append(rec.to_dict())
        await self._save()
        return rec

    async def recall_similar(self, workflow_name: str, workflow_type: str = "") -> list[WorkflowRecord]:
        await self._load()
        results = []
        for r in self._records:
            if workflow_type and r.get("workflow_type") != workflow_type:
                continue
            if workflow_name.lower() in r.get("workflow_name", "").lower():
                results.append(WorkflowRecord(**{k: v for k, v in r.items() if k in WorkflowRecord.__dataclass_fields__}))
        return results[:10]

    async def get_best_practices(self, workflow_type: str) -> list[str]:
        await self._load()
        successful = [r for r in self._records if r.get("workflow_type") == workflow_type and r.get("success")]
        if not successful:
            return [f"No recorded best practices for {workflow_type} yet."]
        try:
            ai = get_ai_client()
            lessons_text = "; ".join(l for r in successful[-10:] for l in r.get("lessons", []))
            resp = await ai.complete(
                system="Best practices synthesizer.",
                user=f"Synthesize top 3 best practices from these lessons for {workflow_type}: {lessons_text[:500]}",
                model=AIModel.STRATEGY, max_tokens=200,
            )
            if resp.success and resp.content:
                return [l.strip() for l in resp.content.strip().split("\n") if l.strip()][:5]
        except Exception:
            pass
        all_lessons = [l for r in successful for l in r.get("lessons", [])]
        return list(set(all_lessons))[:5]

    def success_rate(self, workflow_type: str = "") -> float:
        records = [r for r in self._records if not workflow_type or r.get("workflow_type") == workflow_type]
        if not records:
            return 0.0
        return round(sum(1 for r in records if r.get("success")) / len(records), 2)

    def failed_workflows(self, workflow_type: str = "") -> list[dict]:
        return [r for r in self._records if not r.get("success") and
                (not workflow_type or r.get("workflow_type") == workflow_type)]

    def workflow_analytics(self) -> dict:
        by_type: dict = {}
        durations = []
        for r in self._records:
            wt = r.get("workflow_type", "unknown")
            by_type[wt] = by_type.get(wt, 0) + 1
            if r.get("duration_seconds"):
                durations.append(r["duration_seconds"])
        return {
            "total_records": len(self._records),
            "success_rate_pct": round(self.success_rate() * 100, 1),
            "by_type": by_type,
            "avg_duration_seconds": round(sum(durations) / len(durations), 1) if durations else 0.0,
        }


_instance: Optional[WorkflowMemory] = None


def get_workflow_memory() -> WorkflowMemory:
    global _instance
    if _instance is None:
        _instance = WorkflowMemory()
    return _instance
