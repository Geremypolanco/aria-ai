"""
multimodal.py — Multimodal capabilities for ARIA AI.

Inspired by Gemini Omni:
  - Image analysis with text (image + question → answer)
  - Image editing via natural instruction ("remove the background", "make it brighter")
  - Video description and analysis (frame sampling)
  - OCR: extracts text from images
  - Document/diagram analysis

Uses Claude (vision) for analysis and HF for transformations.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import httpx

from apps.core.tools.web_tools import _assert_public_url

logger = logging.getLogger("aria.multimodal")


class MultimodalEngine:
    """
    ARIA's multimodal engine.
    Analyzes images and videos, and transforms visual content via instruction.
    """

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=60.0)

    # ── IMAGE ANALYSIS ────────────────────────────────────────────────

    async def analyze_image(
        self,
        image_url: str = "",
        image_bytes: bytes = b"",
        question: str = "Describe this image in detail.",
        language: str = "es",
    ) -> dict[str, Any]:
        """
        Analyzes an image with Claude Vision.
        Accepts a URL or raw bytes.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client

            client = get_ai_client()

            if image_url and not image_bytes:
                await _assert_public_url(image_url)
                resp = await self._http.get(image_url, timeout=20)
                image_bytes = resp.content

            if not image_bytes:
                return {"success": False, "error": "No image provided"}

            img_b64 = base64.standard_b64encode(image_bytes).decode()

            analysis = await client.analyze_image(
                image_base64=img_b64,
                question=question,
            )

            return {
                "success": True,
                "analysis": analysis,
                "language": language,
            }

        except Exception as exc:
            logger.error("[Multimodal] analyze_image error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def extract_text(self, image_url: str = "", image_bytes: bytes = b"") -> dict[str, Any]:
        """OCR: extracts visible text from an image."""
        return await self.analyze_image(
            image_url=image_url,
            image_bytes=image_bytes,
            question="Extract ALL visible text in this image, exactly as it appears, preserving structure and formatting.",
        )

    async def analyze_chart(self, image_url: str = "", image_bytes: bytes = b"") -> dict[str, Any]:
        """Analyzes charts, tables, and diagrams."""
        return await self.analyze_image(
            image_url=image_url,
            image_bytes=image_bytes,
            question=(
                "Analyze this chart/table/diagram. Extract: "
                "1) Visualization type, "
                "2) Key data and values, "
                "3) Trends or patterns, "
                "4) Main conclusions."
            ),
        )

    async def analyze_document(
        self, image_url: str = "", image_bytes: bytes = b""
    ) -> dict[str, Any]:
        """Analyzes documents, screenshots, receipts, etc."""
        return await self.analyze_image(
            image_url=image_url,
            image_bytes=image_bytes,
            question=(
                "Analyze this document. Extract: "
                "title, date, parties/sections, key information, "
                "and any important data (numbers, names, dates, amounts)."
            ),
        )

    # ── IMAGE EDITING VIA INSTRUCTION ────────────────────────────────

    async def edit_image(
        self,
        image_url: str = "",
        image_bytes: bytes = b"",
        instruction: str = "",
    ) -> dict[str, Any]:
        """
        Edits an image via a natural-language instruction.
        Uses HF's InstructPix2Pix as the editing engine.
        """
        from apps.core.config import settings

        if not settings.hf_key:
            return {"success": False, "error": "HF_TOKEN not configured"}

        try:
            if image_url and not image_bytes:
                await _assert_public_url(image_url)
                resp = await self._http.get(image_url, timeout=20)
                image_bytes = resp.content

            if not image_bytes:
                return {"success": False, "error": "No image provided"}

            img_b64 = base64.standard_b64encode(image_bytes).decode()

            headers = {"Authorization": f"Bearer {settings.hf_key}"}
            payload = {
                "inputs": instruction,
                "image": img_b64,
            }

            res = await self._http.post(
                "https://api-inference.huggingface.co/models/timbrooks/instruct-pix2pix",
                headers=headers,
                json=payload,
                timeout=60,
            )

            if res.status_code == 200:
                return {
                    "success": True,
                    "image_bytes": res.content,
                    "instruction": instruction,
                }
            return {
                "success": False,
                "error": f"HF InstructPix2Pix: {res.status_code} {res.text[:200]}",
            }

        except Exception as exc:
            logger.error("[Multimodal] edit_image error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def remove_background(
        self, image_url: str = "", image_bytes: bytes = b""
    ) -> dict[str, Any]:
        """Removes the background from an image."""
        from apps.core.config import settings

        if not settings.hf_key:
            return {"success": False, "error": "HF_TOKEN not configured"}

        try:
            if image_url and not image_bytes:
                await _assert_public_url(image_url)
                resp = await self._http.get(image_url, timeout=20)
                image_bytes = resp.content

            headers = {"Authorization": f"Bearer {settings.hf_key}"}
            res = await self._http.post(
                "https://api-inference.huggingface.co/models/briaai/RMBG-1.4",
                headers=headers,
                content=image_bytes,
                timeout=60,
            )

            if res.status_code == 200:
                return {"success": True, "image_bytes": res.content}
            return {"success": False, "error": f"RMBG: {res.status_code}"}

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── VIDEO ANALYSIS ─────────────────────────────────────────────────

    async def analyze_video_url(
        self,
        video_url: str,
        question: str = "Describe this video in detail.",
        max_frames: int = 4,
    ) -> dict[str, Any]:
        """
        Analyzes a video by downloading key frames and analyzing each one with Claude Vision.
        Combines the analyses into a coherent description.
        """
        try:
            # Download video
            await _assert_public_url(video_url)
            resp = await self._http.get(video_url, timeout=30)
            if resp.status_code != 200:
                return {"success": False, "error": f"Cannot download video: {resp.status_code}"}

            video_bytes = resp.content
            return await self.analyze_video_bytes(video_bytes, question, max_frames)

        except Exception as exc:
            logger.error("[Multimodal] analyze_video_url error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def analyze_video_bytes(
        self,
        video_bytes: bytes,
        question: str = "Describe this video in detail.",
        max_frames: int = 4,
    ) -> dict[str, Any]:
        """Extract frames from video bytes and analyze with vision."""
        try:
            frames = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._extract_frames(video_bytes, max_frames)
            )

            if not frames:
                return {"success": False, "error": "Could not extract frames from the video"}

            # Analyze each frame
            tasks = [
                self.analyze_image(
                    image_bytes=frame,
                    question=f"Frame {i+1}/{len(frames)}: {question}",
                )
                for i, frame in enumerate(frames)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            analyses = [
                r.get("analysis", "") for r in results if isinstance(r, dict) and r.get("success")
            ]

            if not analyses:
                return {"success": False, "error": "Could not analyze any frame"}

            # Synthesize into coherent description
            from apps.core.tools.ai_client import AIModel, get_ai_client

            client = get_ai_client()
            synthesis = await client.complete(
                model=AIModel.FAST,
                system="You are a video analyst. Synthesize the frame analyses into a coherent, fluid description of the whole video.",
                user=(
                    f"Analysis of {len(analyses)} video frames:\n\n"
                    + "\n\n".join(f"Frame {i+1}: {a}" for i, a in enumerate(analyses))
                    + f"\n\nOriginal question: {question}\n\nSynthesize into a complete answer."
                ),
            )

            if not synthesis.success:
                return {"success": False, "error": synthesis.error or "Video synthesis failed"}

            return {
                "success": True,
                "analysis": synthesis.content,
                "frames_analyzed": len(analyses),
            }

        except Exception as exc:
            logger.error("[Multimodal] analyze_video_bytes error: %s", exc)
            return {"success": False, "error": str(exc)}

    def _extract_frames(self, video_bytes: bytes, max_frames: int = 4) -> list[bytes]:
        """Extract evenly-spaced frames from video using OpenCV or ffmpeg."""
        try:
            import os
            import tempfile

            import cv2
            import numpy as np  # noqa: F401

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(video_bytes)
                tmp = f.name

            cap = cv2.VideoCapture(tmp)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total <= 0:
                cap.release()
                os.unlink(tmp)
                return []

            indices = [int(total * i / max_frames) for i in range(max_frames)]
            frames = []
            for idx in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                if ret:
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    frames.append(buf.tobytes())

            cap.release()
            os.unlink(tmp)
            return frames

        except ImportError:
            # Fallback: treat first ~65KB as a JPEG if it starts with JPEG header
            if video_bytes[:2] == b"\xff\xd8":
                return [video_bytes[:65536]]
            return []
        except Exception as exc:
            logger.warning("[Multimodal] frame extraction failed: %s", exc)
            return []

    # ── SKETCH / IMAGE TO DESCRIPTION ────────────────────────────────────

    async def sketch_to_description(
        self, image_url: str = "", image_bytes: bytes = b""
    ) -> dict[str, Any]:
        """
        Converts a sketch into a detailed description for image generation.
        Useful for turning visual ideas into prompts.
        """
        return await self.analyze_image(
            image_url=image_url,
            image_bytes=image_bytes,
            question=(
                "This is a sketch. Generate a detailed description to use as an image-generation "
                "prompt: describe colors, style, composition, lighting, "
                "and all visual elements precisely. Format: direct description in English "
                "ready to use as a prompt."
            ),
        )

    async def image_to_prompt(
        self, image_url: str = "", image_bytes: bytes = b""
    ) -> dict[str, Any]:
        """
        Generates an image-generation prompt from an existing image.
        For replicating the style or recreating the image.
        """
        return await self.analyze_image(
            image_url=image_url,
            image_bytes=image_bytes,
            question=(
                "Generate a detailed prompt in English that reproduces this image exactly. "
                "Include: artistic style, dominant colors, composition, lighting, "
                "specific elements, technical quality. Only the prompt, no explanations."
            ),
        )

    async def close(self) -> None:
        await self._http.aclose()


_engine: MultimodalEngine | None = None


def get_multimodal() -> MultimodalEngine:
    global _engine
    if _engine is None:
        _engine = MultimodalEngine()
    return _engine
