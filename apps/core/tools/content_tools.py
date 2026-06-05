"""
content_tools.py — Herramientas de creación de contenido multimedia.
Cloudinary, Pexels, ElevenLabs, FLUX.1, Airtable.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.content_tools")


class ContentTools:
    """Herramientas de creación y gestión de contenido multimedia."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=60.0)

    # ── CLOUDINARY ────────────────────────────────────────

    async def cloudinary_upload(
        self,
        image_data: bytes,
        public_id: Optional[str] = None,
        folder: str = "aria-ai",
    ) -> dict[str, Any]:
        """Sube una imagen a Cloudinary y devuelve la URL pública."""
        if not settings.CLOUDINARY_CLOUD_NAME or not settings.CLOUDINARY_API_KEY:
            return {"success": False, "error": "Cloudinary no configurado"}
        try:
            import hashlib, hmac, time as _time

            timestamp = str(int(_time.time()))
            params_to_sign = f"folder={folder}&timestamp={timestamp}"
            if public_id:
                params_to_sign = f"folder={folder}&public_id={public_id}&timestamp={timestamp}"

            signature = hmac.new(
                settings.CLOUDINARY_API_SECRET.encode() if settings.CLOUDINARY_API_SECRET else b"",
                params_to_sign.encode(),
                hashlib.sha1,
            ).hexdigest()

            encoded = base64.b64encode(image_data).decode()
            data = {
                "file": f"data:image/jpeg;base64,{encoded}",
                "api_key": settings.CLOUDINARY_API_KEY,
                "timestamp": timestamp,
                "signature": signature,
                "folder": folder,
            }
            if public_id:
                data["public_id"] = public_id

            res = await self._http.post(
                f"https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/image/upload",
                data=data,
            )
            if res.status_code == 200:
                result = res.json()
                url = result.get("secure_url", "")
                logger.info("[ContentTools] Imagen subida a Cloudinary: %s", url[:80])
                return {"success": True, "url": url, "public_id": result.get("public_id")}
            return {"success": False, "error": f"Cloudinary HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[ContentTools] Error Cloudinary upload: %s", exc)
            return {"success": False, "error": str(exc)}

    async def cloudinary_upload_url(
        self, image_url: str, folder: str = "aria-ai", public_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Sube una imagen desde URL a Cloudinary."""
        if not settings.CLOUDINARY_CLOUD_NAME or not settings.CLOUDINARY_API_KEY:
            return {"success": False, "error": "Cloudinary no configurado"}
        try:
            import hashlib, hmac, time as _time

            timestamp = str(int(_time.time()))
            params_to_sign = f"folder={folder}&timestamp={timestamp}"
            signature = hmac.new(
                settings.CLOUDINARY_API_SECRET.encode() if settings.CLOUDINARY_API_SECRET else b"",
                params_to_sign.encode(),
                hashlib.sha1,
            ).hexdigest()

            res = await self._http.post(
                f"https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/image/upload",
                data={
                    "file": image_url,
                    "api_key": settings.CLOUDINARY_API_KEY,
                    "timestamp": timestamp,
                    "signature": signature,
                    "folder": folder,
                },
            )
            if res.status_code == 200:
                result = res.json()
                return {"success": True, "url": result.get("secure_url"), "public_id": result.get("public_id")}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def cloudinary_transform_url(
        self,
        public_id: str,
        width: int = 800,
        height: int = 600,
        crop: str = "fill",
        quality: str = "auto",
    ) -> str:
        """Genera una URL de Cloudinary con transformaciones."""
        if not settings.CLOUDINARY_CLOUD_NAME:
            return ""
        return (
            f"https://res.cloudinary.com/{settings.CLOUDINARY_CLOUD_NAME}/image/upload"
            f"/w_{width},h_{height},c_{crop},q_{quality}/{public_id}"
        )

    # ── PEXELS ────────────────────────────────────────────

    async def pexels_search(
        self, query: str, per_page: int = 5, orientation: str = "landscape"
    ) -> list[dict[str, Any]]:
        """Busca fotos de stock en Pexels."""
        if not settings.PEXELS_API_KEY:
            logger.warning("[ContentTools] PEXELS_API_KEY no configurado")
            return []
        try:
            res = await self._http.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": settings.PEXELS_API_KEY},
                params={"query": query, "per_page": per_page, "orientation": orientation},
            )
            if res.status_code == 200:
                photos = res.json().get("photos", [])
                return [
                    {
                        "id": p.get("id"),
                        "url": p.get("url"),
                        "photographer": p.get("photographer"),
                        "src_original": p.get("src", {}).get("original"),
                        "src_large": p.get("src", {}).get("large"),
                        "src_medium": p.get("src", {}).get("medium"),
                        "alt": p.get("alt", ""),
                    }
                    for p in photos
                ]
            logger.warning("[ContentTools] Pexels HTTP %d", res.status_code)
        except Exception as exc:
            logger.error("[ContentTools] Error Pexels: %s", exc)
        return []

    async def pexels_get_curated(self, per_page: int = 5) -> list[dict[str, Any]]:
        """Obtiene fotos curadas de Pexels."""
        if not settings.PEXELS_API_KEY:
            return []
        try:
            res = await self._http.get(
                "https://api.pexels.com/v1/curated",
                headers={"Authorization": settings.PEXELS_API_KEY},
                params={"per_page": per_page},
            )
            if res.status_code == 200:
                return res.json().get("photos", [])
        except Exception:
            pass
        return []

    # ── ELEVENLABS ────────────────────────────────────────

    async def elevenlabs_tts(
        self,
        text: str,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",
        model_id: str = "eleven_multilingual_v2",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
    ) -> dict[str, Any]:
        """Genera audio con ElevenLabs TTS."""
        if not settings.ELEVENLABS_API_KEY:
            return {"success": False, "error": "ELEVENLABS_API_KEY no configurado"}
        try:
            res = await self._http.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": settings.ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text[:2500],
                    "model_id": model_id,
                    "voice_settings": {
                        "stability": stability,
                        "similarity_boost": similarity_boost,
                    },
                },
            )
            if res.status_code == 200:
                audio_bytes = res.content
                audio_b64 = base64.b64encode(audio_bytes).decode()
                logger.info("[ContentTools] Audio ElevenLabs generado: %d bytes", len(audio_bytes))
                return {
                    "success": True,
                    "audio_base64": audio_b64,
                    "size_bytes": len(audio_bytes),
                    "content_type": "audio/mpeg",
                }
            return {"success": False, "error": f"ElevenLabs HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[ContentTools] Error ElevenLabs: %s", exc)
            return {"success": False, "error": str(exc)}

    async def elevenlabs_get_voices(self) -> list[dict[str, Any]]:
        """Lista las voces disponibles en ElevenLabs."""
        if not settings.ELEVENLABS_API_KEY:
            return []
        try:
            res = await self._http.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
            )
            if res.status_code == 200:
                return [
                    {
                        "voice_id": v.get("voice_id"),
                        "name": v.get("name"),
                        "category": v.get("category"),
                        "labels": v.get("labels", {}),
                    }
                    for v in res.json().get("voices", [])
                ]
        except Exception:
            pass
        return []

    # ── FLUX.1 IMAGE GENERATION ───────────────────────────

    async def flux_generate_image(
        self,
        prompt: str,
        model: str = "black-forest-labs/FLUX.1-schnell",
        width: int = 1024,
        height: int = 1024,
    ) -> dict[str, Any]:
        """Genera imagen con FLUX.1 via HuggingFace."""
        if not settings.HF_TOKEN:
            return {"success": False, "error": "HF_TOKEN no configurado"}
        try:
            res = await self._http.post(
                f"https://api-inference.huggingface.co/models/{model}",
                headers={"Authorization": f"Bearer {settings.HF_TOKEN}"},
                json={
                    "inputs": prompt,
                    "parameters": {"width": width, "height": height},
                },
            )
            if res.status_code == 200 and res.headers.get("content-type", "").startswith("image"):
                image_b64 = base64.b64encode(res.content).decode()
                logger.info("[ContentTools] Imagen FLUX.1 generada: %d bytes", len(res.content))
                return {
                    "success": True,
                    "image_base64": image_b64,
                    "image_bytes": res.content,
                    "size_bytes": len(res.content),
                    "content_type": res.headers.get("content-type", "image/jpeg"),
                }
            if res.status_code == 503:
                return {"success": False, "error": "Modelo en cold start (503) — reintentar en 30s"}
            return {"success": False, "error": f"HuggingFace HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[ContentTools] Error FLUX.1: %s", exc)
            return {"success": False, "error": str(exc)}

    async def generate_and_upload_image(
        self, prompt: str, public_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Genera una imagen con FLUX.1 y la sube a Cloudinary."""
        flux_result = await self.flux_generate_image(prompt)
        if not flux_result.get("success"):
            return flux_result

        image_bytes = flux_result.get("image_bytes", b"")
        cloud_result = await self.cloudinary_upload(image_bytes, public_id=public_id)

        return {
            "success": cloud_result.get("success", False),
            "image_url": cloud_result.get("url"),
            "public_id": cloud_result.get("public_id"),
            "source": "flux.1 + cloudinary",
        }

    # ── AIRTABLE ──────────────────────────────────────────

    async def airtable_create_record(
        self, base_id: str, table_name: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """Crea un registro en Airtable."""
        if not settings.AIRTABLE_TOKEN:
            return {"success": False, "error": "AIRTABLE_TOKEN no configurado"}
        try:
            res = await self._http.post(
                f"https://api.airtable.com/v0/{base_id}/{table_name}",
                headers={
                    "Authorization": f"Bearer {settings.AIRTABLE_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"fields": fields},
            )
            if res.status_code in (200, 201):
                return {"success": True, "record": res.json()}
            return {"success": False, "error": f"Airtable HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def airtable_list_records(
        self,
        base_id: str,
        table_name: str,
        max_records: int = 20,
        filter_formula: Optional[str] = None,
    ) -> dict[str, Any]:
        """Lista registros de una tabla de Airtable."""
        if not settings.AIRTABLE_TOKEN:
            return {"success": False, "error": "AIRTABLE_TOKEN no configurado"}
        try:
            params: dict[str, Any] = {"maxRecords": max_records}
            if filter_formula:
                params["filterByFormula"] = filter_formula

            res = await self._http.get(
                f"https://api.airtable.com/v0/{base_id}/{table_name}",
                headers={"Authorization": f"Bearer {settings.AIRTABLE_TOKEN}"},
                params=params,
            )
            if res.status_code == 200:
                return {"success": True, "records": res.json().get("records", [])}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── GOOGLE CUSTOM SEARCH ──────────────────────────────

    async def google_search(self, query: str, num: int = 10) -> list[dict[str, Any]]:
        """Búsqueda via Google Custom Search API."""
        if not settings.GOOGLE_API_KEY:
            return []
        try:
            res = await self._http.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": settings.GOOGLE_API_KEY,
                    "q": query,
                    "num": min(num, 10),
                },
            )
            if res.status_code == 200:
                return res.json().get("items", [])
            logger.warning("[ContentTools] Google Search HTTP %d", res.status_code)
        except Exception as exc:
            logger.error("[ContentTools] Error Google Search: %s", exc)
        return []

    async def close(self) -> None:
        await self._http.aclose()


# ── SINGLETON ─────────────────────────────────────────────
_instance: Optional[ContentTools] = None


def get_content_tools() -> ContentTools:
    global _instance
    if _instance is None:
        _instance = ContentTools()
    return _instance
