"""
canva_tools.py — Creación de diseños via Canva Connect API.
Genera imágenes, infografías y materiales de marketing automáticamente.
"""
from __future__ import annotations
import logging
from typing import Any, Optional
import httpx
from apps.core.config import settings

logger = logging.getLogger("aria.canva_tools")
CANVA_API = "https://api.canva.com/rest/v1"


class CanvaTools:
    """Diseño automatizado via Canva Connect API."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._access_token: Optional[str] = None

    async def _get_token(self) -> Optional[str]:
        """Obtiene access token via OAuth2 client credentials."""
        if self._access_token:
            return self._access_token
        if not settings.CANVA_CLIENT_ID or not settings.CANVA_CLIENT_SECRET:
            return None
        try:
            import base64
            creds = base64.b64encode(
                f"{settings.CANVA_CLIENT_ID}:{settings.CANVA_CLIENT_SECRET}".encode()
            ).decode()
            res = await self._http.post(
                "https://api.canva.com/rest/v1/oauth/token",
                headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials", "scope": "design:content:write asset:read"},
            )
            if res.status_code == 200:
                self._access_token = res.json().get("access_token")
                return self._access_token
        except Exception as exc:
            logger.error("[CanvaTools] Auth error: %s", exc)
        return None

    async def list_designs(self, limit: int = 10) -> dict[str, Any]:
        """Lista los diseños existentes en Canva."""
        token = await self._get_token()
        if not token:
            return {"success": False, "error": "Canva no configurado (CLIENT_ID/SECRET)"}
        try:
            res = await self._http.get(
                f"{CANVA_API}/designs",
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": limit},
            )
            if res.status_code == 200:
                designs = res.json().get("items", [])
                return {
                    "success": True,
                    "designs": [{"id": d["id"], "title": d.get("title", ""), "url": d.get("view_url", "")} for d in designs],
                    "count": len(designs),
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.error("[CanvaTools] list_designs error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def create_design_from_template(
        self,
        design_type: str = "SOCIAL_MEDIA_POST",
        title: str = "ARIA AI Post",
    ) -> dict[str, Any]:
        """Crea un nuevo diseño en Canva."""
        token = await self._get_token()
        if not token:
            return {"success": False, "error": "Canva no configurado"}
        try:
            res = await self._http.post(
                f"{CANVA_API}/designs",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"design_type": {"type": design_type}, "title": title},
            )
            if res.status_code in (200, 201):
                data = res.json().get("design", {})
                return {
                    "success": True,
                    "design_id": data.get("id"),
                    "edit_url": data.get("edit_url", ""),
                    "title": title,
                }
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[CanvaTools] create_design error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def export_design(self, design_id: str, format: str = "PNG") -> dict[str, Any]:
        """Exporta un diseño de Canva como imagen."""
        token = await self._get_token()
        if not token:
            return {"success": False, "error": "Canva no configurado"}
        try:
            res = await self._http.post(
                f"{CANVA_API}/exports",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"design_id": design_id, "format": {"type": format}},
            )
            if res.status_code in (200, 201):
                export = res.json().get("export", {})
                return {
                    "success": True,
                    "export_id": export.get("id"),
                    "status": export.get("status"),
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
