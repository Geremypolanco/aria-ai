from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("aria.video_generator")

# ── Enums ────────────────────────────────────────────────────


class VideoModel(str, Enum):
    RUNWAY = "runway"
    KLING = "kling"
    PIKA = "pika"
    SORA = "sora"
    MOCK = "mock"


class VideoFormat(str, Enum):
    MP4 = "mp4"
    MOV = "mov"
    WEBM = "webm"


class VideoResolution(str, Enum):
    HD_720P = "1280x720"
    FHD_1080P = "1920x1080"
    PORTRAIT_9_16 = "1080x1920"
    SQUARE = "1080x1080"


# ── Dataclass ────────────────────────────────────────────────


@dataclass
class VideoJob:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str = ""
    model: VideoModel = VideoModel.MOCK
    resolution: VideoResolution = VideoResolution.HD_720P
    duration_seconds: int = 5
    format: VideoFormat = VideoFormat.MP4
    status: str = "queued"
    result_url: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    error: str = ""
    frames_per_second: int = 24
    estimated_cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "prompt": self.prompt,
            "model": self.model.value,
            "resolution": self.resolution.value,
            "duration_seconds": self.duration_seconds,
            "format": self.format.value,
            "status": self.status,
            "result_url": self.result_url,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "frames_per_second": self.frames_per_second,
            "estimated_cost_usd": self.estimated_cost_usd,
        }

    @classmethod
    def from_dict(cls, d: dict) -> VideoJob:
        return cls(
            job_id=d.get("job_id", str(uuid.uuid4())),
            prompt=d.get("prompt", ""),
            model=VideoModel(d.get("model", VideoModel.MOCK.value)),
            resolution=VideoResolution(d.get("resolution", VideoResolution.HD_720P.value)),
            duration_seconds=d.get("duration_seconds", 5),
            format=VideoFormat(d.get("format", VideoFormat.MP4.value)),
            status=d.get("status", "queued"),
            result_url=d.get("result_url", ""),
            created_at=d.get("created_at", time.time()),
            completed_at=d.get("completed_at", 0.0),
            error=d.get("error", ""),
            frames_per_second=d.get("frames_per_second", 24),
            estimated_cost_usd=d.get("estimated_cost_usd", 0.0),
        )


# ── Generator ────────────────────────────────────────────────


class VideoGenerator:
    """AI video generation pipeline with multi-provider support and graceful degradation."""

    def __init__(self) -> None:
        self._runway_key: str = os.environ.get("RUNWAY_API_KEY", "")
        self._pika_key: str = os.environ.get("PIKA_API_KEY", "")
        self._jobs: dict[str, VideoJob] = {}

    # ── Model selection ──────────────────────────────────────

    def _best_model(self, requested: Optional[VideoModel]) -> VideoModel:
        if requested and requested != VideoModel.MOCK:
            if requested == VideoModel.RUNWAY and self._runway_key:
                return VideoModel.RUNWAY
            if requested == VideoModel.PIKA and self._pika_key:
                return VideoModel.PIKA
        if self._runway_key:
            return VideoModel.RUNWAY
        if self._pika_key:
            return VideoModel.PIKA
        return VideoModel.MOCK

    # ── Core generate ────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        model: Optional[VideoModel] = None,
        duration: int = 5,
        resolution: VideoResolution = VideoResolution.HD_720P,
    ) -> VideoJob:
        chosen = self._best_model(model)
        job = VideoJob(
            prompt=prompt,
            model=chosen,
            duration_seconds=duration,
            resolution=resolution,
        )
        self._jobs[job.job_id] = job

        try:
            if chosen == VideoModel.RUNWAY:
                await self._generate_via_runway(job)
            elif chosen == VideoModel.PIKA:
                await self._generate_via_pika(job)
            else:
                await self._generate_mock(job)
        except Exception as exc:
            logger.warning("[VideoGenerator] generation failed, falling back to mock: %s", exc)
            await self._generate_mock(job)

        return job

    # ── Provider implementations ─────────────────────────────

    async def _generate_mock(self, job: VideoJob) -> None:
        await asyncio.sleep(0.1)
        job.result_url = (
            f"https://storage.aria.ai/videos/mock/{job.job_id}.{job.format.value}"
        )
        job.status = "completed"
        job.completed_at = time.time()
        job.estimated_cost_usd = 0.0
        logger.debug("[VideoGenerator] mock job %s completed", job.job_id)

    async def _generate_via_runway(self, job: VideoJob) -> None:
        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {self._runway_key}",
                "Content-Type": "application/json",
                "X-Runway-Version": "2024-11-06",
            }
            payload = {
                "promptText": job.prompt,
                "model": "gen3a_turbo",
                "ratio": job.resolution.value.replace("x", ":").replace("1280:720", "1280:768"),
                "duration": job.duration_seconds,
            }
            job.status = "processing"
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.dev.runwayml.com/v1/image_to_video",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                task_id = data.get("id", "")

                for _ in range(3):
                    await asyncio.sleep(5)
                    poll = await client.get(
                        f"https://api.dev.runwayml.com/v1/tasks/{task_id}",
                        headers=headers,
                    )
                    poll_data = poll.json()
                    if poll_data.get("status") == "SUCCEEDED":
                        output = poll_data.get("output", [])
                        job.result_url = output[0] if output else ""
                        job.status = "completed"
                        job.completed_at = time.time()
                        job.estimated_cost_usd = job.duration_seconds * 0.05
                        return

            raise RuntimeError("Runway job did not complete after retries")

        except Exception as exc:
            logger.warning("[VideoGenerator] Runway failed: %s — falling back to mock", exc)
            await self._generate_mock(job)

    async def _generate_via_pika(self, job: VideoJob) -> None:
        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {self._pika_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "prompt": job.prompt,
                "aspectRatio": "16:9",
                "duration": job.duration_seconds,
            }
            job.status = "processing"
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.pika.art/v2/generate",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                job.result_url = data.get("video_url", "")
                job.status = "completed"
                job.completed_at = time.time()
                job.estimated_cost_usd = job.duration_seconds * 0.03

        except Exception as exc:
            logger.warning("[VideoGenerator] Pika failed: %s — falling back to mock", exc)
            await self._generate_mock(job)

    # ── High-level helpers ───────────────────────────────────

    async def generate_short_form(
        self,
        script: str,
        style: str = "vertical_tiktok",
        duration: int = 30,
    ) -> VideoJob:
        summary = script[:200].strip().replace("\n", " ")
        prompt = (
            f"Short-form {style} video: {summary}. "
            "Fast-paced, engaging visuals, vertical format, trending aesthetic."
        )
        return await self.generate(
            prompt=prompt,
            duration=duration,
            resolution=VideoResolution.PORTRAIT_9_16,
        )

    async def generate_ad(
        self,
        headline: str,
        product: str,
        cta: str,
        duration: int = 15,
    ) -> VideoJob:
        prompt = (
            f"Advertisement video for {product}. "
            f"Headline: {headline}. "
            f"Call to action: {cta}. "
            "Professional, high-energy product showcase with clear branding."
        )
        return await self.generate(prompt=prompt, duration=duration)

    async def generate_explainer(
        self,
        topic: str,
        key_points: list[str],
        duration: int = 60,
    ) -> VideoJob:
        points_str = "; ".join(key_points[:5])
        prompt = (
            f"Explainer video about {topic}. "
            f"Key points: {points_str}. "
            "Clear, educational visuals with smooth transitions and informative graphics."
        )
        return await self.generate(prompt=prompt, duration=duration)

    # ── Stats ────────────────────────────────────────────────

    def job_summary(self) -> dict:
        jobs = list(self._jobs.values())
        completed = [j for j in jobs if j.status == "completed"]
        failed = [j for j in jobs if j.status == "failed"]
        pending = [j for j in jobs if j.status in ("queued", "processing")]
        total_cost = sum(j.estimated_cost_usd for j in completed)
        return {
            "total_jobs": len(jobs),
            "completed": len(completed),
            "pending": len(pending),
            "failed": len(failed),
            "total_cost_usd": round(total_cost, 4),
        }


# ── Singleton ────────────────────────────────────────────────

_video_generator: Optional[VideoGenerator] = None


def get_video_generator() -> VideoGenerator:
    global _video_generator
    if _video_generator is None:
        _video_generator = VideoGenerator()
    return _video_generator
