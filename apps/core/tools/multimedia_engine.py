"""
multimedia_engine.py — Procesamiento Multimedia para ARIA AI.

Integra Whisper y ComfyUI para:
  - Transcripción de audio y video (Whisper)
  - Generación y edición avanzada de imágenes (ComfyUI / Stable Diffusion)
  - Creación de activos visuales para campañas

Referencia:
  - Whisper: https://github.com/openai/whisper
  - ComfyUI: https://github.com/comfyanonymous/ComfyUI
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("aria.multimedia")

# ── Whisper Import con fallback ──────────────────────────────────────────────
try:
    import whisper
    WHISPER_AVAILABLE = True
    logger.info("[Whisper] Librería cargada correctamente.")
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("[Whisper] whisper no instalado.")

# ── ComfyUI API Client ───────────────────────────────────────────────────────
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class AriaMultimediaEngine:
    """
    Motor Multimedia de ARIA.
    Gestiona la generación y procesamiento de activos visuales y auditivos.
    """

    def __init__(self, comfy_url: str = "http://localhost:8188") -> None:
        self.comfy_url = comfy_url
        self._whisper_model = None

    async def transcribe_audio(self, file_path: str) -> str:
        """Transcribe un archivo de audio usando Whisper."""
        if not WHISPER_AVAILABLE:
            return "Whisper no disponible para transcripción."

        try:
            if self._whisper_model is None:
                self._whisper_model = whisper.load_model("base")
            
            result = self._whisper_model.transcribe(file_path)
            return result.get("text", "")
        except Exception as exc:
            logger.error("[Multimedia] Error en Whisper: %s", exc)
            return f"Error transcribiendo audio: {exc}"

    async def generate_image(self, prompt: str, output_path: str):
        """Genera una imagen usando la API de ComfyUI."""
        if not HTTPX_AVAILABLE:
            return "HTTPX no disponible para conectar con ComfyUI."

        logger.info("[Multimedia] Generando imagen con ComfyUI: %s", prompt)
        # Aquí se enviaría el workflow JSON a la API de ComfyUI
        return f"Imagen generada y guardada en {output_path} (Simulado ComfyUI)."


# ── Singleton ────────────────────────────────────────────────────────────────
_multimedia_instance: AriaMultimediaEngine | None = None

def get_multimedia_engine() -> AriaMultimediaEngine:
    """Retorna el singleton del motor multimedia."""
    global _multimedia_instance
    if _multimedia_instance is None:
        _multimedia_instance = AriaMultimediaEngine()
    return _multimedia_instance
