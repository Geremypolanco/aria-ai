"""
multimodal.py — Capacidades multimodales de ARIA AI.

Inspirado en Gemini Omni:
  - Análisis de imágenes con texto (imagen + pregunta → respuesta)
  - Edición de imagen por instrucción natural ("quita el fondo", "hazlo más brillante")
  - Descripción y análisis de video (frame sampling)
  - OCR: extrae texto de imágenes
  - Análisis de documentos/diagramas

Usa Claude (vision) para análisis y HF para transformaciones.
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
    Motor multimodal de ARIA.
    Analiza imágenes, videos, y transforma contenido visual por instrucción.
    """

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=60.0)

    # ── ANÁLISIS DE IMAGEN ────────────────────────────────────────────────

    async def analyze_image(
        self,
        image_url: str = "",
        image_bytes: bytes = b"",
        question: str = "Describe esta imagen en detalle.",
        language: str = "es",
    ) -> dict[str, Any]:
        """
        Analiza una imagen con Claude Vision.
        Acepta URL o bytes directos.
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
        """OCR: extrae texto visible en una imagen."""
        return await self.analyze_image(
            image_url=image_url,
            image_bytes=image_bytes,
            question="Extrae TODO el texto visible en esta imagen, exactamente como aparece, preservando estructura y formato.",
        )

    async def analyze_chart(self, image_url: str = "", image_bytes: bytes = b"") -> dict[str, Any]:
        """Analiza gráficas, tablas y diagramas."""
        return await self.analyze_image(
            image_url=image_url,
            image_bytes=image_bytes,
            question=(
                "Analiza este gráfico/tabla/diagrama. Extrae: "
                "1) Tipo de visualización, "
                "2) Datos clave y valores, "
                "3) Tendencias o patrones, "
                "4) Conclusiones principales."
            ),
        )

    async def analyze_document(
        self, image_url: str = "", image_bytes: bytes = b""
    ) -> dict[str, Any]:
        """Analiza documentos, capturas de pantalla, recibos, etc."""
        return await self.analyze_image(
            image_url=image_url,
            image_bytes=image_bytes,
            question=(
                "Analiza este documento. Extrae: "
                "título, fecha, partes/secciones, información clave, "
                "y cualquier dato importante (números, nombres, fechas, importes)."
            ),
        )

    # ── EDICIÓN DE IMAGEN POR INSTRUCCIÓN ────────────────────────────────

    async def edit_image(
        self,
        image_url: str = "",
        image_bytes: bytes = b"",
        instruction: str = "",
    ) -> dict[str, Any]:
        """
        Edita imagen por instrucción en lenguaje natural.
        Usa InstructPix2Pix de HF como motor de edición.
        """
        from apps.core.config import settings

        if not settings.hf_key:
            return {"success": False, "error": "HF_TOKEN no configurado"}

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
        """Elimina el fondo de una imagen."""
        from apps.core.config import settings

        if not settings.hf_key:
            return {"success": False, "error": "HF_TOKEN no configurado"}

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

    # ── ANÁLISIS DE VIDEO ─────────────────────────────────────────────────

    async def analyze_video_url(
        self,
        video_url: str,
        question: str = "Describe este video en detalle.",
        max_frames: int = 4,
    ) -> dict[str, Any]:
        """
        Analiza un video descargando frames clave y analizando cada uno con Claude Vision.
        Combina los análisis en una descripción coherente.
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
        question: str = "Describe este video en detalle.",
        max_frames: int = 4,
    ) -> dict[str, Any]:
        """Extract frames from video bytes and analyze with vision."""
        try:
            frames = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._extract_frames(video_bytes, max_frames)
            )

            if not frames:
                return {"success": False, "error": "No se pudieron extraer frames del video"}

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
                return {"success": False, "error": "No se pudo analizar ningún frame"}

            # Synthesize into coherent description
            from apps.core.tools.ai_client import AIModel, get_ai_client

            client = get_ai_client()
            synthesis = await client.complete(
                model=AIModel.FAST,
                system="Eres un analista de video. Sintetiza los análisis de frames en una descripción coherente y fluida del video completo.",
                user=(
                    f"Análisis de {len(analyses)} frames de video:\n\n"
                    + "\n\n".join(f"Frame {i+1}: {a}" for i, a in enumerate(analyses))
                    + f"\n\nPregunta original: {question}\n\nSintetiza en una respuesta completa."
                ),
            )

            if not synthesis.success:
                return {"success": False, "error": synthesis.error or "Síntesis de video falló"}

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
        Convierte un sketch/boceto en una descripción detallada para generación de imagen.
        Útil para convertir ideas visuales en prompts.
        """
        return await self.analyze_image(
            image_url=image_url,
            image_bytes=image_bytes,
            question=(
                "Este es un boceto o sketch. Genera una descripción detallada para usarla como prompt "
                "de generación de imagen: describe colores, estilo, composición, iluminación, "
                "y todos los elementos visuales con precisión. Formato: descripción directa en inglés "
                "lista para usar como prompt."
            ),
        )

    async def image_to_prompt(
        self, image_url: str = "", image_bytes: bytes = b""
    ) -> dict[str, Any]:
        """
        Genera un prompt de generación de imagen a partir de una imagen existente.
        Para replicar el estilo o recrear la imagen.
        """
        return await self.analyze_image(
            image_url=image_url,
            image_bytes=image_bytes,
            question=(
                "Genera un prompt detallado en inglés que reproduzca esta imagen exactamente. "
                "Incluye: estilo artístico, colores dominantes, composición, iluminación, "
                "elementos específicos, calidad técnica. Solo el prompt, sin explicaciones."
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
