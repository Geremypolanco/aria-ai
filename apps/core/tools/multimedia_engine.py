"""
multimedia_engine.py — Multimedia Processing for ARIA AI.

Integrates Whisper and ComfyUI for:
  - Audio and video transcription (Whisper)
  - Advanced image generation and editing (ComfyUI / Stable Diffusion)
  - Creation of visual assets for campaigns

Reference:
  - Whisper: https://github.com/openai/whisper
  - ComfyUI: https://github.com/comfyanonymous/ComfyUI
"""

from __future__ import annotations

import logging

logger = logging.getLogger("aria.multimedia")

# ── Whisper import with fallback ──────────────────────────────────────────────
try:
    import whisper

    WHISPER_AVAILABLE = True
    logger.info("[Whisper] Library loaded successfully.")
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("[Whisper] whisper not installed.")

# ── ComfyUI API Client ───────────────────────────────────────────────────────
try:
    import httpx  # noqa: F401

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class AriaMultimediaEngine:
    """
    ARIA's Multimedia Engine.
    Manages generation and processing of visual and audio assets.
    """

    def __init__(self, comfy_url: str = "http://localhost:8188") -> None:
        self.comfy_url = comfy_url
        self._whisper_model = None

    async def transcribe_audio(self, file_path: str) -> str:
        """Transcribes an audio file using Whisper."""
        if not WHISPER_AVAILABLE:
            return "Whisper not available for transcription."

        try:
            if self._whisper_model is None:
                self._whisper_model = whisper.load_model("base")

            result = self._whisper_model.transcribe(file_path)
            return result.get("text", "")
        except Exception as exc:
            logger.error("[Multimedia] Whisper error: %s", exc)
            return f"Error transcribing audio: {exc}"

    async def generate_image(self, prompt: str, output_path: str):
        """Generates an image using the ComfyUI API."""
        if not HTTPX_AVAILABLE:
            return "HTTPX not available to connect with ComfyUI."

        logger.info("[Multimedia] Generating image with ComfyUI: %s", prompt)
        # This is where the workflow JSON would be sent to the ComfyUI API
        return f"Image generated and saved to {output_path} (Simulated ComfyUI)."


# ── Singleton ────────────────────────────────────────────────────────────────
_multimedia_instance: AriaMultimediaEngine | None = None


def get_multimedia_engine() -> AriaMultimediaEngine:
    """Returns the multimedia engine singleton."""
    global _multimedia_instance
    if _multimedia_instance is None:
        _multimedia_instance = AriaMultimediaEngine()
    return _multimedia_instance
