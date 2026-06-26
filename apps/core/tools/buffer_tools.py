"""
buffer_tools.py — Automatización de redes sociales via Buffer API.
Publica en Twitter/X, LinkedIn, Facebook, Instagram automáticamente.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.buffer_tools")
BUFFER_API = "https://api.bufferapp.com/1"


class BufferTools:
    """Publicación automatizada en redes sociales via Buffer."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=20.0)
        self._token = settings.BUFFER_TOKEN

    async def get_profiles(self) -> dict[str, Any]:
        """Obtiene todos los perfiles conectados en Buffer."""
        if not self._token:
            return {"success": False, "error": "BUFFER_TOKEN no configurado"}
        try:
            res = await self._http.get(
                f"{BUFFER_API}/profiles.json",
                params={"access_token": self._token},
            )
            if res.status_code == 200:
                profiles = res.json()
                return {
                    "success": True,
                    "profiles": [
                        {
                            "id": p["id"],
                            "service": p["service"],
                            "handle": p.get("formatted_username", ""),
                        }
                        for p in profiles
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.error("[BufferTools] get_profiles error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def post_update(
        self,
        text: str,
        profile_ids: list[str] | None = None,
        now: bool = False,
        media_url: str | None = None,
    ) -> dict[str, Any]:
        """Publica un update en todos (o algunos) perfiles conectados."""
        if not self._token:
            return {"success": False, "error": "BUFFER_TOKEN no configurado"}
        try:
            # Si no se dan IDs, obtener todos los perfiles
            if not profile_ids:
                profiles_res = await self.get_profiles()
                if not profiles_res.get("success"):
                    return profiles_res
                profile_ids = [p["id"] for p in profiles_res.get("profiles", [])]

            if not profile_ids:
                return {"success": False, "error": "No hay perfiles conectados en Buffer"}

            payload: dict[str, Any] = {
                "text": text,
                "profile_ids[]": profile_ids,
                "access_token": self._token,
            }
            if now:
                payload["now"] = "true"
            if media_url:
                payload["media[link]"] = media_url

            res = await self._http.post(
                f"{BUFFER_API}/updates/create.json",
                data=payload,
            )
            if res.status_code == 200:
                data = res.json()
                updates = data.get("updates", [])
                logger.info("[BufferTools] %d updates creados", len(updates))
                return {
                    "success": True,
                    "updates_created": len(updates),
                    "profile_ids": profile_ids,
                    "text_preview": text[:100],
                }
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[BufferTools] post_update error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def get_pending_updates(self, profile_id: str) -> dict[str, Any]:
        """Obtiene los posts pendientes en la cola de un perfil."""
        if not self._token:
            return {"success": False, "error": "BUFFER_TOKEN no configurado"}
        try:
            res = await self._http.get(
                f"{BUFFER_API}/profiles/{profile_id}/updates/pending.json",
                params={"access_token": self._token},
            )
            if res.status_code == 200:
                data = res.json()
                updates = data.get("updates", [])
                return {"success": True, "count": len(updates), "updates": updates[:5]}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def analyze_best_posting_times(self, niche: str, language: str = "es") -> list[str]:
        """Genera los mejores horarios de publicación basados en el nicho."""
        schedules = {
            "marketing": ["09:00", "13:00", "18:00", "21:00"],
            "tech": ["08:00", "12:00", "17:00", "20:00"],
            "ecommerce": ["10:00", "14:00", "19:00", "22:00"],
            "finance": ["07:00", "12:00", "16:00", "20:00"],
            "default": ["09:00", "13:00", "18:00", "21:00"],
        }
        for key in schedules:
            if key in niche.lower():
                return schedules[key]
        return schedules["default"]
