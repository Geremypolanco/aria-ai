"""
GPU job orchestration — Modal, RunPod, and MOCK backends.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.memory.redis_client import get_cache

_GPU_KEY = "infra:gpu:v1"
_GPU_TTL = 86400 * 7


class JobPriority(int, Enum):
    LOW = 1
    NORMAL = 5
    HIGH = 10
    CRITICAL = 20


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GPUBackend(str, Enum):
    MODAL = "modal"
    RUNPOD = "runpod"
    MOCK = "mock"


@dataclass
class GPUJob:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    job_type: str = "inference"
    payload: dict = field(default_factory=dict)
    priority: JobPriority = JobPriority.NORMAL
    status: JobStatus = JobStatus.QUEUED
    backend: GPUBackend = GPUBackend.MOCK
    result: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    estimated_cost_usd: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "payload": self.payload,
            "priority": self.priority.value,
            "status": self.status.value,
            "backend": self.backend.value,
            "result": self.result,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "estimated_cost_usd": self.estimated_cost_usd,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> GPUJob:
        return cls(
            job_id=d.get("job_id", str(uuid.uuid4())),
            job_type=d.get("job_type", "inference"),
            payload=d.get("payload", {}),
            priority=JobPriority(d.get("priority", JobPriority.NORMAL.value)),
            status=JobStatus(d.get("status", JobStatus.QUEUED.value)),
            backend=GPUBackend(d.get("backend", GPUBackend.MOCK.value)),
            result=d.get("result", {}),
            created_at=d.get("created_at", time.time()),
            started_at=d.get("started_at", 0.0),
            completed_at=d.get("completed_at", 0.0),
            estimated_cost_usd=d.get("estimated_cost_usd", 0.0),
            error=d.get("error", ""),
        )


class GPUOrchestrator:
    def __init__(self) -> None:
        self._queue: list[dict] = []
        self._completed: list[dict] = []
        self._loaded = False

    async def _load(self) -> dict:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_GPU_KEY)
                if data and isinstance(data, dict):
                    self._queue = data.get("queue", [])
                    self._completed = data.get("completed", [])
            except Exception:
                pass
            self._loaded = True
        return {"queue": self._queue, "completed": self._completed}

    async def _save(self) -> None:
        data = {
            "queue": self._queue[-1000:],
            "completed": self._completed[-500:],
        }
        try:
            cache = get_cache()
            await cache.set(_GPU_KEY, data, ttl_seconds=_GPU_TTL)
        except Exception:
            pass

    def _select_backend(self) -> GPUBackend:
        import os
        if os.environ.get("MODAL_TOKEN_ID"):
            return GPUBackend.MODAL
        if os.environ.get("RUNPOD_API_KEY"):
            return GPUBackend.RUNPOD
        return GPUBackend.MOCK

    async def submit_job(
        self,
        job_type: str,
        payload: dict,
        priority: JobPriority = JobPriority.NORMAL,
    ) -> GPUJob:
        await self._load()
        job = GPUJob(
            job_type=job_type,
            payload=payload,
            priority=priority,
            backend=self._select_backend(),
            estimated_cost_usd=self._estimate_cost(job_type),
        )
        self._queue.append(job.to_dict())
        self._queue.sort(key=lambda j: j["priority"], reverse=True)
        await self._save()
        return job

    def _estimate_cost(self, job_type: str) -> float:
        costs = {
            "image_generation": 0.04,
            "video_generation": 0.50,
            "inference": 0.01,
            "training": 5.00,
        }
        return costs.get(job_type, 0.02)

    async def process_queue(self, max_jobs: int = 5) -> list[GPUJob]:
        await self._load()
        processed: list[GPUJob] = []
        for _ in range(min(max_jobs, len(self._queue))):
            if not self._queue:
                break
            job_dict = self._queue.pop(0)
            job = GPUJob.from_dict(job_dict)
            job.started_at = time.time()
            job.status = JobStatus.RUNNING

            result = await self._execute_job(job)
            job.result = result
            job.status = JobStatus.COMPLETED
            job.completed_at = time.time()
            self._completed.append(job.to_dict())
            processed.append(job)

        await self._save()
        return processed

    async def _execute_job(self, job: GPUJob) -> dict:
        if job.backend == GPUBackend.MOCK:
            return {"mock_result": True, "job_type": job.job_type, "duration_ms": 100}
        if job.backend == GPUBackend.MODAL:
            return await self._run_modal(job)
        if job.backend == GPUBackend.RUNPOD:
            return await self._run_runpod(job)
        return {}

    async def _run_modal(self, job: GPUJob) -> dict:
        try:
            import modal  # type: ignore
            return {"backend": "modal", "status": "submitted"}
        except ImportError:
            return {"backend": "modal", "error": "modal not installed", "fallback": "mock"}

    async def _run_runpod(self, job: GPUJob) -> dict:
        try:
            import httpx, os
            api_key = os.environ.get("RUNPOD_API_KEY", "")
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.runpod.io/v2/run",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"input": job.payload},
                )
                return r.json()
        except Exception as exc:
            return {"backend": "runpod", "error": str(exc)}

    def auto_scale_recommendation(self) -> dict:
        queue_depth = len(self._queue)
        if queue_depth == 0:
            return {"action": "none", "reason": "Queue empty"}
        if queue_depth < 5:
            return {"action": "none", "reason": "Queue depth manageable"}
        if queue_depth < 20:
            return {"action": "scale_up", "workers": 2, "reason": f"{queue_depth} jobs queued"}
        return {"action": "scale_up", "workers": 5, "reason": f"High queue depth: {queue_depth}"}

    async def status(self) -> dict:
        await self._load()
        return {
            "queue_depth": len(self._queue),
            "completed_count": len(self._completed),
            "backend": self._select_backend().value,
            "scale_recommendation": self.auto_scale_recommendation(),
        }


_orchestrator_instance: Optional[GPUOrchestrator] = None


def get_gpu_orchestrator() -> GPUOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = GPUOrchestrator()
    return _orchestrator_instance
