"""
Enterprise image generation pipeline supporting multiple backends.
Backends: Flux, SDXL (stub), Ideogram, DALL-E, and Mock (always available).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

import httpx

from apps.core.tools.ai_client import get_ai_client

logger = logging.getLogger("aria.image_generator")


# ── Enums ──────────────────────────────────────────────────────────────────────


class ImageModel(StrEnum):
    FLUX = "flux"
    SDXL = "sdxl"
    IDEOGRAM = "ideogram"
    DALLE = "dalle"
    MOCK = "mock"


class ImageFormat(StrEnum):
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"


class ImageSize(StrEnum):
    SQUARE_512 = "512x512"
    SQUARE_1024 = "1024x1024"
    LANDSCAPE = "1792x1024"
    PORTRAIT = "1024x1792"
    THUMBNAIL = "320x180"


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class GenerationConfig:
    steps: int = 30
    guidance_scale: float = 7.5
    seed: int = -1
    style_preset: str = ""
    quality: str = "standard"


@dataclass
class ImageJob:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str = ""
    negative_prompt: str = ""
    model: ImageModel = ImageModel.FLUX
    size: ImageSize = ImageSize.SQUARE_1024
    format: ImageFormat = ImageFormat.PNG
    status: str = "queued"
    result_url: str = ""
    result_b64: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    error: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "model": self.model.value,
            "size": self.size.value,
            "format": self.format.value,
            "status": self.status,
            "result_url": self.result_url,
            "result_b64": self.result_b64,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ImageJob:
        return cls(
            job_id=d.get("job_id", str(uuid.uuid4())),
            prompt=d.get("prompt", ""),
            negative_prompt=d.get("negative_prompt", ""),
            model=ImageModel(d.get("model", ImageModel.FLUX.value)),
            size=ImageSize(d.get("size", ImageSize.SQUARE_1024.value)),
            format=ImageFormat(d.get("format", ImageFormat.PNG.value)),
            status=d.get("status", "queued"),
            result_url=d.get("result_url", ""),
            result_b64=d.get("result_b64", ""),
            created_at=d.get("created_at", time.time()),
            completed_at=d.get("completed_at", 0.0),
            error=d.get("error", ""),
            metadata=d.get("metadata", {}),
        )


# ── ImageGenerator ─────────────────────────────────────────────────────────────


class ImageGenerator:
    """Enterprise image generation pipeline with multi-backend support."""

    def __init__(self) -> None:
        self._flux_api_key: str = os.getenv("FLUX_API_KEY", "")
        self._ideogram_api_key: str = os.getenv("IDEOGRAM_API_KEY", "")
        self._openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
        self._queue: list[dict] = []
        self._completed: list[dict] = []

        # Determine best available model
        if self._flux_api_key:
            self._default_model = ImageModel.FLUX
        elif self._ideogram_api_key:
            self._default_model = ImageModel.IDEOGRAM
        elif self._openai_api_key:
            self._default_model = ImageModel.DALLE
        else:
            self._default_model = ImageModel.MOCK
            logger.info("No image API keys found — using MOCK model")

    # ── Public API ─────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        model: ImageModel | None = None,
        size: ImageSize = ImageSize.SQUARE_1024,
        config: GenerationConfig | None = None,
        negative_prompt: str = "",
    ) -> ImageJob:
        """Generate an image and return the completed ImageJob."""
        chosen_model = model or self._default_model
        if config is None:
            config = GenerationConfig()

        job = ImageJob(
            prompt=prompt,
            negative_prompt=negative_prompt,
            model=chosen_model,
            size=size,
        )
        self._queue.append(job.to_dict())

        try:
            if chosen_model == ImageModel.FLUX and self._flux_api_key:
                await self._generate_via_flux(job, config)
            elif chosen_model == ImageModel.IDEOGRAM and self._ideogram_api_key:
                await self._generate_via_ideogram(job, config)
            elif chosen_model == ImageModel.DALLE:
                await self._generate_via_dalle(job, config)
            else:
                await self._generate_mock(job, config)
        except Exception as exc:
            logger.warning("Generation failed (%s), falling back to mock: %s", chosen_model, exc)
            await self._generate_mock(job, config)

        # Move from queue to completed
        self._queue = [q for q in self._queue if q.get("job_id") != job.job_id]
        self._completed.append(job.to_dict())
        return job

    # ── Backends ───────────────────────────────────────────────────────────────

    async def _generate_mock(self, job: ImageJob, config: GenerationConfig) -> None:
        """Simulate generation with a short delay."""
        await asyncio.sleep(0.1)
        job.result_url = f"https://placehold.co/{job.size.value}.png?text={job.job_id[:8]}"
        job.status = "completed"
        job.completed_at = time.time()
        job.metadata["backend"] = "mock"

    async def _generate_via_flux(self, job: ImageJob, config: GenerationConfig) -> None:
        """Call Flux Pro API (bfl.ml)."""
        payload = {
            "prompt": job.prompt,
            "width": int(job.size.value.split("x")[0]),
            "height": int(job.size.value.split("x")[1]),
            "steps": config.steps,
            "guidance": config.guidance_scale,
        }
        if config.seed >= 0:
            payload["seed"] = config.seed

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.bfl.ml/v1/flux-pro",
                headers={
                    "x-key": self._flux_api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        job.result_url = data.get("sample") or data.get("url") or data.get("output", "")
        job.status = "completed"
        job.completed_at = time.time()
        job.metadata["backend"] = "flux"
        job.metadata["flux_id"] = data.get("id", "")

    async def _generate_via_ideogram(self, job: ImageJob, config: GenerationConfig) -> None:
        """Call Ideogram API."""
        payload = {
            "image_request": {
                "prompt": job.prompt,
                "negative_prompt": job.negative_prompt or None,
                "aspect_ratio": _size_to_ideogram_ratio(job.size),
                "model": "V_2",
                "style_type": config.style_preset.upper() if config.style_preset else "GENERAL",
            }
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.ideogram.ai/generate",
                headers={
                    "Api-Key": self._ideogram_api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        images = data.get("data", [])
        if images:
            job.result_url = images[0].get("url", "")
        job.status = "completed"
        job.completed_at = time.time()
        job.metadata["backend"] = "ideogram"

    async def _generate_via_dalle(self, job: ImageJob, config: GenerationConfig) -> None:
        """Use ai_client if available to call DALL-E, fall back to mock."""
        try:
            client = get_ai_client()
            if client is None:
                raise RuntimeError("AI client not available")

            # DALL-E sizes differ — map to closest supported
            dalle_size = _size_to_dalle(job.size)
            response = await client.generate_image(
                prompt=job.prompt,
                size=dalle_size,
                quality=config.quality,
            )
            job.result_url = response.get("url", "")
            job.result_b64 = response.get("b64_json", "")
            job.status = "completed"
            job.completed_at = time.time()
            job.metadata["backend"] = "dalle"
        except Exception as exc:
            logger.warning("DALL-E generation failed: %s", exc)
            await self._generate_mock(job, config)

    # ── Convenience helpers ────────────────────────────────────────────────────

    async def thumbnail(
        self,
        title: str,
        style: str = "modern",
        brand_colors: list[str] | None = None,
    ) -> ImageJob:
        """Generate a thumbnail-optimised image."""
        color_hint = ""
        if brand_colors:
            color_hint = f", brand colors: {', '.join(brand_colors[:3])}"
        prompt = (
            f"YouTube thumbnail, {style} style, bold text '{title[:40]}', "
            f"eye-catching, high contrast, 8k quality{color_hint}"
        )
        return await self.generate(prompt, size=ImageSize.THUMBNAIL)

    async def product_image(
        self,
        product_name: str,
        background: str = "white studio",
        features: list[str] | None = None,
    ) -> ImageJob:
        """Generate a product shot."""
        feature_hint = ""
        if features:
            feature_hint = f", highlighting: {', '.join(features[:3])}"
        prompt = (
            f"Professional product photography of {product_name}, "
            f"{background} background, clean, high resolution, commercial quality"
            f"{feature_hint}"
        )
        return await self.generate(prompt)

    async def ad_creative(
        self,
        headline: str,
        cta: str,
        brand_style: str = "professional",
    ) -> ImageJob:
        """Generate an ad creative image."""
        prompt = (
            f"Digital advertisement, {brand_style} style, "
            f"headline: '{headline[:60]}', call-to-action: '{cta[:30]}', "
            "visually striking, marketing quality, clean layout"
        )
        return await self.generate(prompt, size=ImageSize.LANDSCAPE)

    async def batch_generate(
        self,
        prompts: list[str],
        model: ImageModel | None = None,
    ) -> list[ImageJob]:
        """Generate multiple images in parallel."""
        tasks = [self.generate(p, model=model) for p in prompts]
        return list(await asyncio.gather(*tasks))

    # ── Stats & lookup ─────────────────────────────────────────────────────────

    def queue_stats(self) -> dict:
        total = len(self._completed)
        successes = sum(1 for j in self._completed if j.get("status") == "completed")
        return {
            "queued": len(self._queue),
            "completed": total,
            "success_rate": round(successes / total, 3) if total else 0.0,
        }

    def get_job(self, job_id: str) -> dict | None:
        """Search in-memory queue and completed list for a job."""
        for collection in (self._completed, self._queue):
            for job in collection:
                if job.get("job_id") == job_id:
                    return job
        return None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _size_to_ideogram_ratio(size: ImageSize) -> str:
    mapping = {
        ImageSize.SQUARE_512: "ASPECT_1_1",
        ImageSize.SQUARE_1024: "ASPECT_1_1",
        ImageSize.LANDSCAPE: "ASPECT_16_9",
        ImageSize.PORTRAIT: "ASPECT_9_16",
        ImageSize.THUMBNAIL: "ASPECT_16_9",
    }
    return mapping.get(size, "ASPECT_1_1")


def _size_to_dalle(size: ImageSize) -> str:
    """Map ImageSize to a DALL-E supported size string."""
    mapping = {
        ImageSize.SQUARE_512: "512x512",
        ImageSize.SQUARE_1024: "1024x1024",
        ImageSize.LANDSCAPE: "1792x1024",
        ImageSize.PORTRAIT: "1024x1792",
        ImageSize.THUMBNAIL: "1024x1024",  # closest DALL-E supports
    }
    return mapping.get(size, "1024x1024")


# ── Singleton ──────────────────────────────────────────────────────────────────

_generator_instance: ImageGenerator | None = None


def get_image_generator() -> ImageGenerator:
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = ImageGenerator()
    return _generator_instance
